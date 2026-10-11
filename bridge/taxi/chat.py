"""Диалог заказа и защита от повторной отправки после тайм-аута/перезапуска."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from .model import ExtraConfirmation, LoginRequired, NotSubmitted, OutcomeUnknown, TaxiError

log = logging.getLogger("taxi")
STATE_KEY = "taxi.order.v1"
HELP = ("Яндекс Go, ваша обычная учётная запись.\n"
        "поездка — начать; откуда <адрес>; куда <адрес>.\n"
        "Адрес выбирается номером из предложений.\n"
        "тарифы; тариф <номер>; цена — расчёт и код подтверждения.\n"
        "заказать <код> — вызвать машину; статус — состояние поездки.\n"
        "отмена — условия отмены; отменить <код> — подтвердить.\n"
        "сброс — очистить адреса, без отмены поездки. !help — эта подсказка.")


class TaxiChat:
    def __init__(self, cfg, storage, backend, notify):
        self.cfg, self.storage, self.backend, self.notify = cfg, storage, backend, notify
        self.lock = asyncio.Lock()
        self.task = None
        self.account = ""
        self.initialized = False
        self.target = 0
        self.choices = ()
        self.have_origin = False
        self.have_destination = False
        self.quote = None
        self.code = ""
        self.expires = 0.0
        self.extra = ""
        self.cancel = None
        self.last_notification = None
        self.last_error = ""
        try:
            self.state = json.loads(storage.get_meta(STATE_KEY, "{}") or "{}")
            if not isinstance(self.state, dict) or self.state.get("phase", "idle") not in (
                    "idle", "submitting", "active", "cancelling"):
                raise ValueError("invalid taxi state")
        except (ValueError, TypeError):
            # Повреждённая запись не является разрешением сделать новый заказ.
            self.state = {"phase": "submitting", "account": "", "order_id": ""}

    def _save(self, phase, order_id=""):
        self.state = {"phase": phase, "account": self.account, "order_id": order_id}
        self.storage.set_meta(STATE_KEY, json.dumps(self.state))

    def _clear_quote(self):
        self.quote, self.code, self.extra = None, "", ""
        self.expires = 0.0
        self.cancel = None

    def _new_code(self):
        # Не повторяется после перезапуска; старый пакет ICQ не подтвердит
        # следующее предложение случайно совпавшим случайным кодом.
        return str(1000 + self.storage.next_seq("taxi_confirmation") % 9000)

    async def _auth(self):
        account = await self.backend.ensure_logged_in()
        if self.account and self.account != account:
            self._clear_quote()
            self.have_origin = self.have_destination = False
            self.initialized = False
        self.account = account
        if self.state.get("phase", "idle") != "idle":
            if self.state.get("account") != account:
                raise TaxiError("Незавершённый заказ относится к другой сессии. "
                                "Войдите в тот же аккаунт и проверьте его поездки.")
        if not self.initialized:
            result = await self._status(refresh=True)
            self.initialized = True
            return result
        return None

    async def _status(self, refresh=False):
        known_id = self.state.get("order_id", "")
        trips = await self.backend.trips(known_id, refresh=refresh)
        active = [t for t in trips if not t.finished]
        if active:
            trip = next((t for t in active if t.order_id == known_id), active[0])
            self._save("active", trip.order_id)
            if self.quote is not None:
                self._clear_quote()
            if self.cancel and (self.cancel[0] != trip.order_id or trip.cancel_state != "free"):
                self.cancel = None
            return trip.text() + (f"\nАктивных поездок: {len(active)}" if len(active) > 1 else ""), trip
        finished = next((t for t in trips if t.order_id == known_id and t.finished), None)
        if finished is not None:
            self._save("idle")
            self._clear_quote()
            return finished.text(), finished
        if self.state.get("phase", "idle") != "idle":
            # Пустой список не доказывает, что запрос на заказ не дошёл.
            # Его ответ мог потеряться, а commit ещё идти на сервере.
            return ("Исход предыдущего запроса не выяснен. Новый заказ заблокирован. "
                    "Проверьте поездки в Яндекс Go; «статус» повторит проверку."), None
        return "Активных поездок нет.", None

    def _idle(self):
        if self.state.get("phase", "idle") != "idle":
            raise TaxiError("Уже есть поездка или незавершённый запрос. Напишите «статус».")

    async def _address(self, target, text):
        self._idle()
        text = self.cfg.taxi_places.get(text.casefold(), text).strip()
        if not text:
            return "Введите адрес после «откуда» или «куда»."
        self._clear_quote()
        self.target = target
        if target == 0:
            self.have_origin = False
        else:
            self.have_destination = False
        self.choices = await self.backend.suggest(target, text, self.cfg.taxi_city)
        if not self.choices:
            return "Адрес не найден. Укажите город, улицу и дом."
        return "Выберите адрес номером:\n" + "\n".join(
            f"{i}. {s}" for i, s in enumerate(self.choices, 1))

    async def _calculate(self, extra=""):
        self._idle()
        if not (self.have_origin and self.have_destination):
            return "Сначала укажите и выберите оба адреса: «откуда …» и «куда …»."
        if not extra:
            await self.backend.dismiss_confirmation()
        quote = await self.backend.quote()
        self.quote, self.code, self.extra = quote, self._new_code(), extra
        self.cancel = None
        self.expires = time.monotonic() + self.cfg.taxi_quote_seconds
        details = f"\nУсловия сайта:\n{extra}" if extra else ""
        return (quote.text() + details + f"\nДля подтверждения: заказать {self.code}\n"
                f"Код действует {self.cfg.taxi_quote_seconds:g} с.")

    async def _order(self, code):
        self._idle()
        if not self.quote or code != self.code:
            return "Нужен текущий код из расчёта. Напишите «цена»."
        if time.monotonic() >= self.expires:
            self._clear_quote()
            return "Расчёт устарел. Напишите «цена» для нового подтверждения."
        current = await self.backend.quote()
        if time.monotonic() >= self.expires:
            self._clear_quote()
            return "Расчёт устарел во время проверки. Напишите «цена» для нового подтверждения."
        if current.stable != self.quote.stable:
            return "Маршрут, цена или оплата изменились.\n" + await self._calculate()
        extra = self.extra
        self._clear_quote()
        # SQLite в autocommit: запись завершается ДО отправки.
        self._save("submitting")
        try:
            result = await self.backend.order(current, extra)
        except NotSubmitted:
            self._save("idle")
            raise
        except OutcomeUnknown as exc:
            self._save("submitting", exc.order_id)
            raise
        except Exception:
            # Любая другая ошибка после начала действия не разрешает повтор.
            raise OutcomeUnknown() from None
        if isinstance(result, ExtraConfirmation):
            self._save("idle")
            return await self._calculate(extra=result.text)
        self._save("idle" if result.finished else "active", result.order_id)
        self.last_notification = result.notification_key
        return result.text()

    async def _cancel_offer(self):
        text, trip = await self._status()
        if trip is None or trip.finished:
            return text
        if trip.cancel_state != "free":
            return ("Сайт не подтверждает бесплатную отмену. "
                    "Условия и платную отмену проверьте в Яндекс Go.\n" + trip.text())
        self.cancel = (trip.order_id, self._new_code(), time.monotonic() + 30)
        return "Сейчас отмена бесплатна. Для подтверждения: отменить " + self.cancel[1]

    async def _cancel_order(self, code):
        if not self.cancel or code != self.cancel[1]:
            return "Сначала напишите «отмена» и получите код подтверждения."
        order_id, _, deadline = self.cancel
        self.cancel = None
        if time.monotonic() >= deadline:
            return "Подтверждение устарело. Напишите «отмена» ещё раз."
        trips = await self.backend.trips(order_id)
        trip = next((t for t in trips if t.order_id == order_id), None)
        if trip is None:
            return "Состояние поездки не удалось проверить. Отмена не отправлена."
        if trip.finished:
            self._save("idle")
            return trip.text()
        if trip.cancel_state != "free":
            return "Условия отмены изменились. Отмена не отправлена; проверьте Яндекс Go."
        self._save("cancelling", order_id)
        try:
            result = await self.backend.cancel(trip)
        except NotSubmitted:
            self._save("active", order_id)
            raise
        except Exception:
            raise TaxiError("Ответ на отмену не получен. Напишите «статус». "
                            "Повторная отмена не отправляется автоматически.") from None
        self._save("idle" if result.finished else "active", result.order_id)
        self.last_notification = result.notification_key
        return result.text()

    async def handle(self, text):
        async with self.lock:
            try:
                # До входа не выполняются даже поиск адреса и расчёт цены.
                initial = await self._auth()
                text = text.strip()
                command, _, value = text.partition(" ")
                command = command.casefold()
                value = value.strip()
                if command in ("!help", "помощь", "help"):
                    return HELP
                if command in ("статус", "status"):
                    result, _ = initial if initial is not None else await self._status(refresh=True)
                    return result
                if command in ("поездка", "новая", "сброс", "!reset"):
                    self._idle()
                    self._clear_quote()
                    self.choices = ()
                    self.have_origin = self.have_destination = False
                    self.target = 0
                    await self.backend.reset_route()
                    return "Откуда ехать? Напишите адрес с городом или «откуда <адрес>»."
                if command in ("откуда", "куда"):
                    return await self._address(0 if command == "откуда" else 1, value)
                if command == "заказать":
                    return await self._order(value)
                if command == "отмена":
                    return await self._cancel_offer()
                if command == "отменить":
                    return await self._cancel_order(value)
                if command == "тариф":
                    self._idle()
                    if not self.quote or not value.isdigit() or not (1 <= int(value) <= len(self.quote.fares)):
                        return "Напишите «тарифы», затем «тариф <номер>»."
                    fare = self.quote.fares[int(value) - 1]
                    self._clear_quote()
                    await self.backend.select_fare(fare.code)
                    return await self._calculate()
                if command in ("цена", "тарифы", "расчёт", "расчет"):
                    result = await self._calculate()
                    if command == "тарифы" and self.quote:
                        result = "\n".join(f"{i}. {f.title}: {f.price}" for i, f in enumerate(self.quote.fares, 1)) + "\n" + result
                    return result
                if text.isdigit() and self.choices:
                    self._idle()
                    index = int(text) - 1
                    if not 0 <= index < len(self.choices):
                        return f"Выберите номер от 1 до {len(self.choices)}."
                    label = await self.backend.choose(self.target, index, self.choices)
                    self.choices = ()
                    if self.target == 0:
                        self.have_origin = True
                        self.target = 1
                        return f"Откуда: {label}\nКуда ехать?"
                    self.have_destination = True
                    if not self.have_origin:
                        self.target = 0
                        return f"Куда: {label}\nТеперь укажите «откуда <адрес>»."
                    return await self._calculate()
                if not self.quote and not self.choices and text:
                    return await self._address(self.target, text)
                return HELP
            except LoginRequired as exc:
                self._clear_quote()
                return str(exc)
            except TaxiError as exc:
                return str(exc)
            except Exception as exc:
                # Ошибки Playwright/HTTP могут содержать URL с секретами.
                log.warning("Яндекс Go: команда не выполнена (%s)", type(exc).__name__)
                return "Яндекс Go сейчас недоступен. Попробуйте «статус» позже."

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self._monitor(), name="yandex-taxi")

    async def _monitor(self):
        from pathlib import Path
        restore = (Path(self.cfg.taxi_session) / "login.ok").is_file()
        while True:
            try:
                async with self.lock:
                    if restore or self.state.get("phase", "idle") != "idle":
                        initial = await self._auth()
                        text, trip = initial if initial is not None else await self._status()
                        restore = False
                        if trip and trip.notification_key != self.last_notification:
                            await self.notify(text)
                            self.last_notification = trip.notification_key
                        self.last_error = ""
            except TaxiError as exc:
                message = str(exc)
                if self.state.get("phase", "idle") != "idle" and message != self.last_error:
                    await self.notify(message)
                self.last_error = message
            except Exception as exc:
                log.warning("Яндекс Go: проверка поездки не выполнена (%s)", type(exc).__name__)
            await asyncio.sleep(self.cfg.taxi_poll_seconds)

    async def close(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        await self.backend.close()
