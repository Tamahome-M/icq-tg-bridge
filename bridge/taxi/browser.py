"""Обращения к штатному веб-клиенту Go после входа в личный аккаунт."""

from __future__ import annotations

import asyncio
from collections import deque
import hashlib
from pathlib import Path
import re
from urllib.parse import urlsplit

from .model import (ExtraConfirmation, Fare, LoginRequired, NotSubmitted,
                    OutcomeUnknown, Quote, TaxiError, Trip)

WEB_URL = "https://taxi.yandex.ru/"
PAGE_JS = Path(__file__).with_name("page.js").read_text(encoding="utf-8")
FIND_STORE = """() => {
    if (window.__tmmTaxiStore) return true;
    const stack = [], seen = new Set();
    for (const root of document.querySelectorAll('#root, #app, body > div')) {
        for (const key of Object.keys(root)) {
            if (key.startsWith('__reactContainer') || key.startsWith('_reactRootContainer')) {
                let fiber = root[key];
                if (fiber?._internalRoot) fiber = fiber._internalRoot.current;
                stack.push(fiber);
            }
        }
    }
    while (stack.length && seen.size < 20000) {
        const fiber = stack.pop();
        if (!fiber || seen.has(fiber)) continue;
        seen.add(fiber);
        const props = fiber.memoizedProps;
        const store = props?.store || props?.value?.store;
        if (store?.getState && store?.dispatch && store.getState().session) {
            window.__tmmTaxiStore = store;
            return true;
        }
        stack.push(fiber.child, fiber.sibling);
    }
    return false;
}"""

ERRORS = {
    "INTERFACE": "Сайт Яндекс Go изменился: нужный обработчик недоступен. Проверьте поездки в Go.",
    "LOADING": "Яндекс Go ещё загружает сессию. Попробуйте позже.",
    "ROUTE": "Нужны два выбранных адреса с городом, улицей и домом.",
    "ESTIMATE": "Стоимость маршрута не получена. Проверьте тариф и способ оплаты на сайте.",
    "ACTIVE": "В Яндекс Go уже есть активная поездка. Напишите «статус».",
    "CHANGED": "Данные на сайте изменились. Напишите «цена» для нового подтверждения.",
    "API": "Яндекс Go не ответил на запрос. Попробуйте «статус» позже.",
}


def error_from_browser(exc, *, before_submit=False):
    message = str(exc)
    if "TMM_TAXI_LOGIN" in message:
        return NotSubmitted(str(LoginRequired())) if before_submit else LoginRequired()
    for key, text in ERRORS.items():
        if "TMM_TAXI_" + key in message:
            return (NotSubmitted if before_submit and key != "API"
                    else TaxiError)(text)
    return TaxiError("Не удалось открыть Яндекс Go. Проверьте браузер и вход на сервере.")


def trip_from_data(data, order_id):
    # Селектор веб-клиента carInfo читает driver; car бывает строкой.
    driver = data.get("driver") or {}
    car = driver.get("car") or {}
    if isinstance(car, str):
        car = {"model": car, "color": driver.get("color"), "number": driver.get("number")}
    currency = (data.get("currency_rules") or {}).get("code", "")
    price = data.get("final_cost")
    return Trip(order_id, str(data["status"]),
                car=" ".join(str(car[k]) for k in ("color", "model") if car.get(k)),
                number=str(car.get("number") or ""), driver=str(driver.get("name") or ""),
                phone=str(driver.get("phone") or ""),
                cancel_state=str((data.get("cancel_state") or {}).get("state") or ""),
                price=f"{price} {currency}".strip() if price is not None else "")


class TaxiBrowser:
    def __init__(self, cfg):
        self.cfg = cfg
        self.pw = self.context = self.page = None
        self.account_id = ""
        self._responses = set()
        self._estimates = deque(maxlen=8)
        self._request_serial = {}
        self._serial = 0
        self._mutations = 0
        self._submitted_id = ""
        self._choices = ()
        self._target = 0

    async def _open(self):
        if self.page is not None and not self.page.is_closed():
            return
        await self.close()
        try:
            from playwright.async_api import async_playwright
            from ..express.browser import open_context, prepare
            prepare()
            self.pw = await async_playwright().start()
            self.context = await open_context(self.pw, self.cfg.taxi_session,
                                              executable=self.cfg.taxi_browser or self.cfg.express_browser,
                                              devtools_port=self.cfg.taxi_devtools_port)
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            self.page.on("request", self._request)
            self.page.on("requestfailed", lambda request: self._request_serial.pop(request, None))
            self.page.on("response", self._response)
            self.page.set_default_timeout(self.cfg.taxi_timeout * 1000)
            await self._load()
        except BaseException:
            await self.close()
            raise

    async def _load(self):
        self._request_serial.clear()
        self._estimates.clear()
        await self.page.goto(WEB_URL, wait_until="domcontentloaded",
                             timeout=self.cfg.taxi_timeout * 1000)
        await self.page.wait_for_function(FIND_STORE)
        await self.page.evaluate(PAGE_JS)
        await self.page.wait_for_function("""() => {
            const s = window.__tmmTaxiStore.getState();
            return s.session?.ui && !s.session.ui.isLoading &&
                s.session.authStatus && s.orderSearch?.nonpersist?.isPersistedOrderInited;
        }""")

    def _request(self, request):
        parsed = urlsplit(request.url)
        if parsed.hostname != "ya-authproxy.taxi.yandex.ru":
            return
        if parsed.path == "/3.0/routestats":
            self._request_serial[request] = self._serial
        if parsed.path in ("/external/3.0/orderdraft", "/external/3.0/ordercommit"):
            self._mutations += 1

    def _response(self, response):
        parsed = urlsplit(response.url)
        if parsed.hostname != "ya-authproxy.taxi.yandex.ru" or parsed.path not in (
                "/3.0/routestats", "/external/3.0/orderdraft"):
            return
        serial = self._request_serial.pop(response.request, -1)
        task = asyncio.create_task(self._read_response(response, parsed.path, serial))
        self._responses.add(task)
        task.add_done_callback(self._responses.discard)

    async def _read_response(self, response, path, serial):
        try:
            if response.status != 200:
                return
            data = await response.json()
            if path == "/external/3.0/orderdraft":
                self._submitted_id = str(data.get("orderid") or "")
            else:
                request = response.request.post_data_json
                self._estimates.append((serial, request, data))
        except Exception:
            pass

    async def ensure_logged_in(self):
        try:
            async with asyncio.timeout(self.cfg.taxi_timeout):
                await self._open()
                snapshot = await self.page.evaluate("window.__tmmTaxi.snapshot()")
        except Exception as exc:
            raise error_from_browser(exc) from None
        if not snapshot["authorized"] or not snapshot["account"]:
            raise LoginRequired()
        if snapshot["loading"]:
            raise TaxiError(ERRORS["LOADING"])
        self.account_id = snapshot["account"]
        return hashlib.sha256(str(self.account_id).encode()).hexdigest()

    async def _action(self, prefix, payload=None, **guard):
        await self.ensure_logged_in()
        try:
            async with asyncio.timeout(self.cfg.taxi_timeout):
                await self.page.evaluate("args => window.__tmmTaxi.action(args)",
                                         {"prefix": prefix, "payload": payload,
                                          "account": self.account_id, **guard})
        except Exception as exc:
            raise error_from_browser(exc, before_submit=True) from None

    def _field(self, target):
        return self.page.locator('textarea[placeholder="Откуда"]' if target == 0
                                 else 'textarea[placeholder^="Куда"]:not([readonly])')

    async def _labels(self):
        labels = await self.page.get_by_role("option").evaluate_all("""es => es.map(e =>
            e.innerText.replace(/\\s+/g, ' ').trim())""")
        return tuple(labels[:5])

    async def suggest(self, target, text, city=""):
        await self.ensure_logged_in()
        await self.dismiss_confirmation()
        if city and city.casefold() not in text.casefold():
            text = city + ", " + text
        await self._field(target).fill(text)
        # Results are tied to this input; an old zero-suggest must not be offered.
        await self.page.wait_for_function("""({index, query}) => {
            const s = window.__tmmTaxiStore.getState();
            const result = s.suggest?.results?.[index];
            const norm = text => String(text || '').trim().replace(/\\s+/g, ' ').toLocaleLowerCase();
            return result?.data && norm(result.lastPart) === norm(query) && !result.isLoading;
        }""", arg={"index": target, "query": text})
        self._choices, self._target = await self._labels(), target
        return self._choices

    async def choose(self, target, index, expected):
        await self.ensure_logged_in()
        if target != self._target or tuple(expected) != self._choices or await self._labels() != self._choices:
            raise TaxiError("Предложения адресов изменились. Повторите «откуда …» или «куда …».")
        await self.page.get_by_role("option").nth(index).click()
        await self.page.wait_for_function("""index => {
            const s = window.__tmmTaxiStore.getState();
            return !s.orderForm.routePointsLoadingStatus[index] && s.orderForm.route[index]?.fullName;
        }""", arg=target)
        route = await self.page.evaluate("i => window.__tmmTaxiStore.getState().orderForm.route[i]", target)
        self._choices = ()
        return route["fullName"] + (f", подъезд {route['porchnumber']}" if route.get("porchnumber") else "")

    async def reset_route(self):
        await self.ensure_logged_in()
        try:
            await self.page.evaluate("window.__tmmTaxi.resetRoute()")
        except Exception as exc:
            raise error_from_browser(exc) from None
        self._choices = ()

    async def select_fare(self, code):
        await self.dismiss_confirmation()
        await self.ensure_logged_in()
        title = await self.page.evaluate("""code => {
            const s = window.__tmmTaxiStore.getState();
            return s.orderEstimate.roads[s.tollRoads.roadType].serviceLevels.find(f => f.class === code)?.name;
        }""", code)
        if not title:
            raise TaxiError("Тариф больше не доступен. Напишите «тарифы» ещё раз.")
        # selectTariff is private to its React component. Use its actual button
        # rather than bypassing the handler with an invented Redux action.
        titles = self.page.locator('[class*="title--"]').filter(has_text=re.compile("^" + re.escape(title) + "$"))
        buttons = self.page.locator('button[class*="button_style_multiline"]').filter(has=titles)
        if await buttons.count() != 1:
            raise TaxiError(ERRORS["INTERFACE"])
        await buttons.click()
        await self.page.wait_for_function("code => window.__tmmTaxiStore.getState().orderEstimate.shared.selectedEstimate === code", arg=code)

    async def dismiss_confirmation(self):
        await self.ensure_logged_in()
        try:
            await self.page.evaluate("window.__tmmTaxi.dismissConfirmation()")
        except Exception as exc:
            raise error_from_browser(exc) from None

    async def quote(self):
        await self.ensure_logged_in()
        road = await self.page.evaluate("window.__tmmTaxiStore.getState().tollRoads.roadType")
        self._serial += 1
        serial = self._serial
        # The exported loadEstimate starts its own per-road requests and returns
        # before they finish. Wait for the selected road and correlate its reply.
        await self._action("order-estimate/loadEstimate")
        try:
            await self.page.wait_for_function("""road => {
                const ui = window.__tmmTaxiStore.getState().orderEstimate.roads[road]?.ui;
                return ui?.wasLoaded && !ui.isLoading;
            }""", arg=road, timeout=self.cfg.taxi_timeout * 1000)
            raw = await self.page.evaluate("window.__tmmTaxi.quote()")
        except Exception as exc:
            raise error_from_browser(exc) from None
        # The guest pickup price is not the price of a two-point trip. Accept
        # only a fresh successful routestats response for these exact points.
        for _ in range(20):
            for seq, request, response in reversed(self._estimates):
                if (seq == serial and request.get("route") == raw["route"]
                        and request.get("payment", {}).get("type") == raw["paymentKey"]["type"]
                        and request.get("payment", {}).get("id") == raw["paymentKey"].get("id")
                        and (not request.get("selected_class") or request["selected_class"] == raw["selected"])
                        and response.get("offer") == raw.get("offer")
                        and response.get("currency_rules", {}).get("code") == raw["currency"]
                        and any(f.get("class") == raw["selected"] and f.get("price_raw") == raw["price"]
                                for f in response.get("service_levels", []))):
                    if request.get("due"):
                        raise TaxiError("На сайте выбрана поездка ко времени. "
                                        "Для заказа через чат переключите её на «сейчас» в браузере.")
                    return Quote(raw["origin"], raw["destination"],
                                 tuple(Fare(**f) for f in raw["fares"]), raw["selected"],
                                 raw["payment"], raw["stable"], raw["guard"])
            await asyncio.sleep(0.1)
        raise TaxiError("Нет подтверждённой стоимости выбранного маршрута. Заказ не отправлен.")

    async def trips(self, known_id="", *, refresh=False):
        await self.ensure_logged_in()
        if refresh and not known_id:
            # One startup resync discovers rides created on another device and
            # drops stale persisted orders. Active polling uses taxiontheway.
            try:
                async with asyncio.timeout(self.cfg.taxi_timeout):
                    await self._load()
            except Exception as exc:
                raise error_from_browser(exc) from None
            await self.ensure_logged_in()
        snapshot = await self.page.evaluate("window.__tmmTaxi.snapshot()")
        ids = [known_id] if known_id else snapshot["ids"]
        if len(ids) > 8:
            raise TaxiError("В аккаунте несколько поездок. Проверьте их в Яндекс Go.")
        result = []
        for order_id in dict.fromkeys(ids):
            try:
                async with asyncio.timeout(self.cfg.taxi_timeout):
                    data = await self.page.evaluate("args => window.__tmmTaxi.trip(args)",
                                                    {"id": order_id, "account": self.account_id})
            except Exception as exc:
                raise error_from_browser(exc) from None
            result.append(trip_from_data(data, order_id))
        return result

    async def _modal_text(self):
        dialogs = self.page.locator('[role="dialog"]:visible, [aria-modal="true"]:visible')
        if not await dialogs.count():
            dialogs = self.page.locator('[class*="modal--"]:visible')
        if not await dialogs.count():
            raise TaxiError("Окно подтверждения сайта не распознано. Проверьте Яндекс Go в браузере.")
        text = (await dialogs.first.inner_text()).strip()
        if not text or len(text) > 3000:
            raise TaxiError("Условия сайта не помещаются в сообщение. Подтвердите их в браузере Go.")
        return text

    async def order(self, quote, extra=""):
        try:
            await self.ensure_logged_in()
            # Verify the native confirmation text again. Changed conditions require
            # another explicit confirmation, never an automatic click-through.
            snapshot = await self.page.evaluate("window.__tmmTaxi.snapshot()")
            if extra and (not snapshot["paidOptions"] or await self._modal_text() != extra):
                raise TaxiError("Условия сайта изменились. Напишите «цена» ещё раз.")
        except Exception as exc:
            raise NotSubmitted(str(exc) if isinstance(exc, TaxiError) else ERRORS["INTERFACE"]) from None
        before = self._mutations
        self._submitted_id = ""
        try:
            await self._action("order-form/orderConfirmStep2" if extra else "order-form/orderConfirm",
                               guard=quote.guard, extra=bool(extra))
        except NotSubmitted:
            raise
        except Exception:
            raise OutcomeUnknown(self._submitted_id) from None
        try:
            deadline = asyncio.get_running_loop().time() + self.cfg.taxi_timeout
            while asyncio.get_running_loop().time() < deadline:
                snapshot = await self.page.evaluate("window.__tmmTaxi.snapshot()")
                if snapshot["paidOptions"] and not extra and self._mutations == before:
                    try:
                        return ExtraConfirmation(await self._modal_text())
                    except TaxiError as exc:
                        raise NotSubmitted(str(exc)) from None
                if snapshot["ids"]:
                    trips = await self.trips(self._submitted_id or snapshot["ids"][0])
                    if trips:
                        return trips[0]
                await asyncio.sleep(0.5)
        except NotSubmitted:
            raise
        except Exception:
            raise OutcomeUnknown(self._submitted_id) from None
        raise OutcomeUnknown(self._submitted_id)

    async def cancel(self, trip):
        await self.ensure_logged_in()
        fresh = (await self.trips(trip.order_id))[0]
        if fresh.cancel_state != "free" or fresh.finished:
            raise NotSubmitted("Условия отмены изменились. Отмена не отправлена.")
        await self._action("order/cancelOrder", orderId=trip.order_id)
        return (await self.trips(trip.order_id))[0]

    async def close(self):
        tasks = list(self._responses)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._responses.clear()
        try:
            if self.context is not None:
                await self.context.close()
        finally:
            self.context = self.page = None
            if self.pw is not None:
                await self.pw.stop()
                self.pw = None
        self._request_serial.clear()
        self._estimates.clear()
