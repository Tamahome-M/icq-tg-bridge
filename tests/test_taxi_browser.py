"""Real Chromium against an isolated web-client fixture; no real rides or credentials."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.config import Config
from bridge.taxi.browser import FIND_STORE, PAGE_JS, TaxiBrowser, trip_from_data
from bridge.taxi.model import ExtraConfirmation, LoginRequired, NotSubmitted, TaxiError

FIXTURE = r'''<!doctype html><html><body><div id="root"></div><script>
const state = {
 session: {authStatus: "authorized", userId: "fixture-account", ui: {isLoading: false}, startupOrderIds: []},
 orderSearch: {persist: {orders: {}, activeOrderId: null}, nonpersist: {isPersistedOrderInited: true}},
 orderForm: {route: [
   {name: "А, 1", fullName: "Москва, А, 1", point: {lon: 37.6, lat: 55.7}, porchnumber: "2"},
   {name: "Б, 2", fullName: "Москва, Б, 2", point: {lon: 37.7, lat: 55.8}}],
   auction: {}, comment: "", PaidOptionsModalVisible: false},
 orderEstimate: {shared: {selectedEstimate: "econom"}, roads: {regular: {
   ui: {isLoading: false, wasLoaded: true}, currencyRules: {code: "RUB"},
   serviceLevels: [{name: "Эконом", class: "econom", price_raw: 300, price: "300 ₽"}],
   estimates: {offer: "old-offer"}}}},
 paymentMethods: {selectedPaymentMethod: {type: "cash"}}, tollRoads: {roadType: "regular"},
 requirements: {}, orderParams: {}, preorder: {}
};
window.fixtureState = state;
window.wrongRoute = false;
window.mutations = [];
const store = {
 getState: () => state,
 dispatch: async action => {
  const {prefix, payload} = action;
  if (prefix === "order-estimate/loadEstimate") {
   const e = state.orderEstimate.roads.regular;
   e.ui.isLoading = true;
   const points = state.orderForm.route.map(p => [p.point.lon, p.point.lat]);
   const response = await fetch("https://ya-authproxy.taxi.yandex.ru/3.0/routestats", {method: "POST",
    body: JSON.stringify({route: window.wrongRoute ? points.slice(0,1) : points,
      payment: state.paymentMethods.selectedPaymentMethod, selected_class: state.orderEstimate.shared.selectedEstimate})});
   const data = await response.json();
   e.serviceLevels = data.service_levels;
   e.currencyRules = data.currency_rules;
   e.estimates = data;
   e.ui.isLoading = false;
  } else if (prefix === "order-estimate/selectTariff") {
   state.orderEstimate.shared.selectedEstimate = payload.tariffCode;
  } else if (prefix === "order-form/orderConfirm") {
   state.orderForm.PaidOptionsModalVisible = true;
   const div = document.createElement('div');
   div.setAttribute('role', 'dialog'); div.textContent = 'Бесплатная отмена первые две минуты.';
   document.body.appendChild(div);
  } else if (prefix === "order-form/orderConfirmStep2") {
   window.mutations.push(prefix);
   await fetch("https://ya-authproxy.taxi.yandex.ru/external/3.0/orderdraft", {method: "POST"});
   await fetch("https://ya-authproxy.taxi.yandex.ru/external/3.0/ordercommit", {method: "POST"});
   state.orderForm.PaidOptionsModalVisible = false;
   document.querySelector('[role="dialog"]').remove();
   state.orderSearch.persist.orders['fixture-order'] = {info: {status: 'search', cancel_state: {state: 'free'}}};
   state.orderSearch.persist.activeOrderId = 'fixture-order';
  } else if (prefix === "order/cancelOrder") {
   window.mutations.push(prefix);
  }
  if (action.type === "order-form/hidePaidOptionsModal") {
   state.orderForm.PaidOptionsModalVisible = false;
   document.querySelector('[role="dialog"]')?.remove();
  }
  return {meta: {requestStatus: 'fulfilled'}};
 }
};
document.querySelector('#root').__reactContainerFixture = {memoizedProps: {value: {store}}, child: null, sibling: null};
function makeAction(prefix) {
 const fn = payload => ({prefix, payload}); fn.typePrefix = prefix; return fn;
}
function estimateFactory() { return {action: makeAction("order-estimate/loadEstimate")}; }
function confirmFactory() { return {action: makeAction("order-form/orderConfirm")}; }
function confirm2Factory() { return {action: makeAction("order-form/orderConfirmStep2")}; }
function cancelFactory() { return {action: makeAction("order/cancelOrder")}; }
function tripFactory() {
 return {request: async function(e) {
  const endpoint = "/3.0/taxiontheway";
  return {data: await (await fetch("https://ya-authproxy.taxi.yandex.ru" + endpoint, {method: 'POST',
    body: JSON.stringify({orderid: e.orderId, id: e.userId, break: e.breakReason})})).json()};
 }};
}
const factories = {estimateFactory, confirmFactory, confirm2Factory, cancelFactory, tripFactory};
const require = key => factories[key](); require.m = factories;
window.webpackChunk_yandex_int_turboapp_taxi = {push: a => a[2](require)};
</script></body></html>'''


@unittest.skipUnless(os.environ.get("TAXI_BROWSER_TESTS"), "set TAXI_BROWSER_TESTS=1 to run Chromium fixtures")
class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(headless=True)
        self.context = await self.browser.new_context()
        self.requests = []
        self.offer = 0
        self.status = "search"

        async def route_handler(route):
            request = route.request
            path = urlsplit(request.url).path
            if request.url == "https://taxi.yandex.ru/":
                await route.fulfill(status=200, content_type="text/html", body=FIXTURE)
                return
            if urlsplit(request.url).hostname != "ya-authproxy.taxi.yandex.ru":
                await route.abort()
                return
            data = request.post_data_json if request.post_data else {}
            self.requests.append((path, data))
            if path == "/3.0/routestats":
                self.offer += 1
                reply = {"service_levels": [{"name": "Эконом", "class": "econom", "price_raw": 300,
                                             "price": "300 ₽"}],
                         "currency_rules": {"code": "RUB"}, "offer": f"offer-{self.offer}"}
            elif path == "/3.0/taxiontheway":
                reply = {"orderid": "fixture-order", "status": self.status,
                         "cancel_state": {"state": "free"}, "driver": {
                             "name": "Водитель", "car": "Белая машина", "number": "А123БВ", "phone": "test-phone"}}
            elif path == "/external/3.0/orderdraft":
                reply = {"orderid": "fixture-order"}
            elif path == "/external/3.0/ordercommit":
                reply = {"orderid": "fixture-order"}
            else:
                await route.abort()
                return
            await route.fulfill(status=200, content_type="application/json", body=json.dumps(reply),
                                headers={"Access-Control-Allow-Origin": "*"})

        await self.context.route("**/*", route_handler)
        self.backend = TaxiBrowser(Config(taxi_timeout=3))
        self.backend.context = self.context
        self.backend.page = await self.context.new_page()
        self.backend.page.on("request", self.backend._request)
        self.backend.page.on("response", self.backend._response)
        await self.backend._load()

    async def asyncTearDown(self):
        await self.backend.close()
        await self.browser.close()
        await self.pw.stop()

    async def test_guest_id_is_not_authenticated(self):
        await self.backend.page.evaluate("fixtureState.session.authStatus='unauthorized'")
        for call in (self.backend.ensure_logged_in, lambda: self.backend.suggest(0, 'Москва'),
                     self.backend.quote, self.backend.trips):
            with self.assertRaises(LoginRequired):
                await call()
        self.assertEqual(self.requests, [])
        self.assertEqual(await self.backend.page.evaluate("mutations"), [])

    async def test_route_estimate_correlated_with_fresh_response(self):
        result = await self.backend.quote()
        self.assertEqual(result.fare.price, "300 RUB")
        self.assertIn("подъезд 2", result.origin)
        self.assertIn("offer-1", result.guard)
        self.assertEqual(self.requests[-1][1]["route"], [[37.6, 55.7], [37.7, 55.8]])

    async def test_pickup_only_price_is_not_trip_price(self):
        await self.backend.page.evaluate("window.wrongRoute=true")
        with self.assertRaisesRegex(TaxiError, "Нет подтверждённой"):
            await self.backend.quote()
        self.assertFalse(any(path.startswith('/external/') for path, _ in self.requests))

    async def test_native_conditions_and_explicit_second_confirmation(self):
        quote = await self.backend.quote()
        extra = await self.backend.order(quote)
        self.assertIsInstance(extra, ExtraConfirmation)
        self.assertFalse(any(path.startswith('/external/') for path, _ in self.requests))
        current = await self.backend.quote()
        self.assertEqual(quote.stable, current.stable)
        result = await self.backend.order(current, extra.text)
        self.assertEqual(result.order_id, 'fixture-order')
        self.assertEqual(result.status, 'search')
        self.assertEqual(result.number, 'А123БВ')
        self.assertEqual([path for path, _ in self.requests if path.startswith('/external/')],
                         ['/external/3.0/orderdraft', '/external/3.0/ordercommit'])

    async def test_atomic_guard_rejects_changed_price(self):
        quote = await self.backend.quote()
        await self.backend.page.evaluate("fixtureState.orderEstimate.roads.regular.serviceLevels[0].price_raw=400")
        with self.assertRaises(NotSubmitted):
            await self.backend.order(quote)
        self.assertEqual(await self.backend.page.evaluate("mutations"), [])
        self.assertFalse(any(path.startswith('/external/') for path, _ in self.requests))

    async def test_atomic_guard_rejects_changed_account(self):
        quote = await self.backend.quote()
        await self.backend.page.evaluate("fixtureState.session.userId='other-account'")
        with self.assertRaises(NotSubmitted):
            await self.backend.order(quote)
        self.assertEqual(await self.backend.page.evaluate("mutations"), [])

    async def test_readonly_status_does_not_cancel(self):
        await self.backend.ensure_logged_in()
        trips = await self.backend.trips('fixture-order')
        self.assertEqual(trips[0].number, 'А123БВ')
        path, payload = self.requests[-1]
        self.assertEqual(path, '/3.0/taxiontheway')
        self.assertNotIn('break', payload)
        self.assertEqual(await self.backend.page.evaluate("mutations"), [])

    async def test_unknown_action_cannot_create_directly(self):
        await self.backend.ensure_logged_in()
        with self.assertRaisesRegex(Exception, "TMM_TAXI_INTERFACE"):
            await self.backend.page.evaluate("""() => window.__tmmTaxi.action({prefix: 'order/createOrder'})""")
        self.assertEqual(await self.backend.page.evaluate("mutations"), [])


if __name__ == "__main__":
    unittest.main()
