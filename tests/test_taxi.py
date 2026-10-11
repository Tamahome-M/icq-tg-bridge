"""Taxi auth, confirmations, crash recovery, routing and free cancellation."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.bridge import Bridge
from bridge.config import Config
from bridge.db import Storage
from bridge.oscar import const as C
from bridge.taxi import TAXI_PEER
from bridge.taxi.browser import TaxiBrowser, trip_from_data
from bridge.taxi.chat import STATE_KEY, TaxiChat
from bridge.taxi.model import (ExtraConfirmation, Fare, LoginRequired, NotSubmitted,
                               OutcomeUnknown, Quote, Trip)


def quote(price="300 RUB", stable="route-price-payment-account", guard="offer-1"):
    return Quote("Москва, А, 1", "Москва, Б, 2", (Fare("econom", "Эконом", price),
                 Fare("business", "Комфорт", "450 RUB")), "econom", "Наличные", stable, guard)


class Backend:
    def __init__(self, storage):
        self.storage = storage
        self.account = "account-one"
        self.logged_in = True
        self.calls = []
        self.current_quote = quote()
        self.current_trips = []
        self.order_result = None
        self.closed = False

    async def ensure_logged_in(self):
        self.calls.append("auth")
        if not self.logged_in:
            raise LoginRequired()
        return self.account

    async def trips(self, known_id="", *, refresh=False):
        self.calls.append(("trips", known_id, refresh))
        return list(self.current_trips)

    async def reset_route(self):
        self.calls.append("reset")

    async def suggest(self, target, text, city):
        self.calls.append(("suggest", target, text, city))
        return ("Москва, А, 1", "Москва, Б, 2")

    async def choose(self, target, index, expected):
        self.calls.append(("choose", target, index))
        return expected[index]

    async def select_fare(self, code):
        self.calls.append(("fare", code))
        self.current_quote = replace(self.current_quote, selected=code, stable="new-fare")

    async def dismiss_confirmation(self):
        self.calls.append("dismiss")

    async def quote(self):
        self.calls.append("quote")
        return self.current_quote

    async def order(self, current, extra=""):
        persisted = json.loads(self.storage.get_meta(STATE_KEY))
        assert persisted["phase"] == "submitting", "marker must precede browser mutation"
        self.calls.append(("order", current, extra))
        if isinstance(self.order_result, Exception):
            raise self.order_result
        if self.order_result is not None:
            result, self.order_result = self.order_result, None
            return result
        trip = Trip("order-one", "search", cancel_state="free")
        self.current_trips = [trip]
        return trip

    async def cancel(self, trip):
        assert json.loads(self.storage.get_meta(STATE_KEY))["phase"] == "cancelling"
        self.calls.append(("cancel", trip.order_id))
        result = replace(trip, status="cancelled")
        self.current_trips = [result]
        return result

    async def close(self):
        self.closed = True


class ChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cfg = Config(db=str(Path(self.temp.name) / "bridge.db"),
                          taxi_session=str(Path(self.temp.name) / "taxi.session"),
                          taxi_places={"дом": "Москва, А, 1"})
        self.storage = Storage(self.cfg.db)
        self.backend = Backend(self.storage)
        self.notifications = []

        async def notify(text):
            self.notifications.append(text)

        self.notify = notify
        self.chat = TaxiChat(self.cfg, self.storage, self.backend, self.notify)

    async def asyncTearDown(self):
        await self.chat.close()
        self.storage.close()
        self.temp.cleanup()

    async def ready(self):
        self.assertIn("Откуда", await self.chat.handle("поездка"))
        self.assertIn("1.", await self.chat.handle("дом"))
        self.assertIn(("suggest", 0, "Москва, А, 1", ""), self.backend.calls)
        self.assertIn("Куда", await self.chat.handle("1"))
        await self.chat.handle("Москва, Б, 2")
        self.assertIn("заказать", await self.chat.handle("2"))
        self.assertTrue(self.chat.code)

    async def test_auth_before_every_command(self):
        self.backend.logged_in = False
        for command in ("поездка", "откуда Москва", "куда Москва", "цена", "тарифы",
                        "заказать 1234", "статус", "отмена", "отменить 1234", "!help"):
            self.assertIn("Сначала войдите", await self.chat.handle(command))
        self.assertEqual(self.backend.calls, ["auth"] * 10)
        self.assertIsNone(self.storage.get_meta(STATE_KEY))

    async def test_address_selection_and_fare(self):
        await self.ready()
        self.assertIn("1. Эконом", await self.chat.handle("тарифы"))
        text = await self.chat.handle("тариф 2")
        self.assertIn("Тариф: Комфорт", text)
        self.assertFalse(any(isinstance(c, tuple) and c[0] == "order" for c in self.backend.calls))

    async def test_confirmation_and_duplicate_packet(self):
        await self.ready()
        code = self.chat.code
        self.assertIn("текущий код", await self.chat.handle("заказать 0000"))
        results = await asyncio.gather(self.chat.handle("заказать " + code),
                                       self.chat.handle("заказать " + code))
        self.assertIn("Ищем машину", results[0])
        self.assertIn("Уже есть поездка", results[1])
        self.assertEqual(sum(isinstance(c, tuple) and c[0] == "order" for c in self.backend.calls), 1)
        self.assertEqual(json.loads(self.storage.get_meta(STATE_KEY))["phase"], "active")

    async def test_expired_confirmation(self):
        await self.ready()
        code = self.chat.code
        self.chat.expires = time.monotonic() - 1
        self.assertIn("устарел", await self.chat.handle("заказать " + code))
        self.assertFalse(any(isinstance(c, tuple) and c[0] == "order" for c in self.backend.calls))

    async def test_changed_price_or_payment_needs_new_code(self):
        await self.ready()
        old = self.chat.code
        self.backend.current_quote = quote("400 RUB", "different-payment-and-price")
        text = await self.chat.handle("заказать " + old)
        self.assertIn("изменились", text)
        self.assertIn("400 RUB", text)
        self.assertNotEqual(old, self.chat.code)
        self.assertIn("текущий код", await self.chat.handle("заказать " + old))
        self.assertFalse(any(isinstance(c, tuple) and c[0] == "order" for c in self.backend.calls))

    async def test_new_offer_same_price_uses_fresh_guard(self):
        await self.ready()
        self.backend.current_quote = replace(self.backend.current_quote, guard="offer-2")
        await self.chat.handle("заказать " + self.chat.code)
        sent = next(c for c in self.backend.calls if isinstance(c, tuple) and c[0] == "order")
        self.assertEqual(sent[1].guard, "offer-2")

    async def test_extra_site_conditions_need_second_confirmation(self):
        await self.ready()
        first = self.chat.code
        self.backend.order_result = ExtraConfirmation("Бесплатная отмена первые 2 минуты.")
        result = await self.chat.handle("заказать " + first)
        self.assertIn("Условия сайта", result)
        self.assertNotEqual(first, self.chat.code)
        second = self.chat.code
        self.assertIn("текущий код", await self.chat.handle("заказать " + first))
        await self.chat.handle("заказать " + second)
        sent = [c for c in self.backend.calls if isinstance(c, tuple) and c[0] == "order"]
        self.assertEqual(sent[-1][2], "Бесплатная отмена первые 2 минуты.")

    async def test_unknown_outcome_survives_restart_empty_history(self):
        await self.ready()
        self.backend.order_result = OutcomeUnknown()
        self.assertIn("не получен", await self.chat.handle("заказать " + self.chat.code))
        old = self.chat
        self.chat = TaxiChat(self.cfg, self.storage, self.backend, self.notify)
        await old.close()
        self.assertIn("заблокирован", await self.chat.handle("статус"))
        self.assertIn("Уже есть поездка", await self.chat.handle("поездка"))
        self.assertEqual(sum(isinstance(c, tuple) and c[0] == "order" for c in self.backend.calls), 1)

    async def test_unknown_order_id_restores_then_finishes(self):
        await self.ready()
        self.backend.order_result = OutcomeUnknown("order-one")
        await self.chat.handle("заказать " + self.chat.code)
        self.backend.current_trips = [Trip("order-one", "waiting", number="А123БВ")]
        self.assertIn("А123БВ", await self.chat.handle("статус"))
        self.backend.current_trips = [Trip("order-one", "complete", price="300 RUB")]
        self.assertIn("завершена", await self.chat.handle("статус"))
        self.assertEqual(self.chat.state["phase"], "idle")

    async def test_proven_no_submission_allows_new_calculation(self):
        await self.ready()
        old = self.chat.code
        self.backend.order_result = NotSubmitted("Проверка отклонила заказ до отправки.")
        self.assertIn("до отправки", await self.chat.handle("заказать " + old))
        self.assertEqual(self.chat.state["phase"], "idle")
        await self.chat.handle("цена")
        self.assertNotEqual(self.chat.code, old)

    async def test_external_order_blocks_draft(self):
        self.backend.current_trips = [Trip("external", "search")]
        self.assertIn("Уже есть поездка", await self.chat.handle("откуда Москва"))
        self.assertFalse(any(isinstance(c, tuple) and c[0] == "suggest" for c in self.backend.calls))

    async def test_account_changed_invalidates_quote(self):
        await self.ready()
        old = self.chat.code
        self.backend.account = "other-account"
        self.assertIn("текущий код", await self.chat.handle("заказать " + old))
        self.assertFalse(self.chat.have_origin)

    async def test_account_changed_cannot_resolve_old_pending_order(self):
        await self.ready()
        self.backend.order_result = OutcomeUnknown()
        await self.chat.handle("заказать " + self.chat.code)
        self.backend.account = "other-account"
        self.assertIn("другой сессии", await self.chat.handle("статус"))
        self.assertEqual(self.chat.state["phase"], "submitting")

    async def test_free_cancel_confirm_and_monitor(self):
        await self.ready()
        await self.chat.handle("заказать " + self.chat.code)
        self.assertIn("Сейчас отмена бесплатна", await self.chat.handle("отмена"))
        code = self.chat.cancel[1]
        await self.chat._status()  # a polling update must not invalidate the code
        self.assertIn("отменена", await self.chat.handle("отменить " + code))
        await self.chat.handle("отменить " + code)
        self.assertEqual(sum(isinstance(c, tuple) and c[0] == "cancel" for c in self.backend.calls), 1)

    async def test_cancel_became_paid_is_not_sent(self):
        await self.ready()
        await self.chat.handle("заказать " + self.chat.code)
        await self.chat.handle("отмена")
        code = self.chat.cancel[1]
        self.backend.current_trips = [Trip("order-one", "waiting", cancel_state="paid")]
        self.assertIn("изменились", await self.chat.handle("отменить " + code))
        self.assertIn("не подтверждает бесплатную", await self.chat.handle("отмена"))
        self.assertFalse(any(isinstance(c, tuple) and c[0] == "cancel" for c in self.backend.calls))

    async def test_corrupt_marker_is_not_treated_as_idle(self):
        self.storage.set_meta(STATE_KEY, "broken")
        self.chat = TaxiChat(self.cfg, self.storage, self.backend, self.notify)
        self.assertIn("другой сессии", await self.chat.handle("поездка"))
        self.assertFalse(any(isinstance(c, tuple) and c[0] == "suggest" for c in self.backend.calls))

    async def test_restart_confirmation_codes_do_not_repeat(self):
        await self.ready()
        first = self.chat.code
        self.chat = TaxiChat(self.cfg, self.storage, self.backend, self.notify)
        await self.ready()
        self.assertNotEqual(first, self.chat.code)


class ConfigTests(unittest.TestCase):
    def test_defaults_and_paths(self):
        self.assertFalse(Config().taxi_enabled)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            text = ('[oscar]\nuin="123456"\n[telegram]\napi_id=1\napi_hash="x"\n'
                    '[taxi]\nenabled=true\nsession="go.session"\ncity="Москва"\n'
                    'poll_seconds=20\n[taxi.places]\n"Дом"="Москва, А, 1"\n')
            path.write_text(text)
            cfg = Config.load(str(path))
            self.assertEqual(cfg.taxi_session, str(Path(directory) / "go.session"))
            self.assertEqual(cfg.taxi_places["дом"], "Москва, А, 1")
            for bad in ("poll_seconds=0", "poll_seconds=nan", "poll_seconds=inf"):
                path.write_text(text.replace("poll_seconds=20", bad))
                with self.assertRaisesRegex(ValueError, "taxi.poll_seconds"):
                    Config.load(str(path))
            path.write_text(text + '[express]\nenabled=true\nsession="go.session"\n')
            with self.assertRaisesRegex(ValueError, "разными профилями"):
                Config.load(str(path))


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_contact_routing_no_telegram_required_and_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = Config(db=str(Path(directory) / "bridge.db"), taxi_enabled=True,
                         tg_api_id=1, tg_api_hash="x", tg_session=str(Path(directory) / "tg.session"),
                         taxi_session=str(Path(directory) / "go.session"),
                         photos_enabled=False, render_enabled=False, avatars=False)
            bridge = Bridge(cfg)
            backend = Backend(bridge.storage)
            backend.logged_in = False
            bridge.taxi.backend = backend
            delivered = []
            async def deliver(uin, text, **kwargs):
                delivered.append((uin, text, kwargs))
            bridge.oscar.deliver = deliver
            try:
                await bridge._apply_roster({})
                contact = bridge.storage.contact_by_peer(TAXI_PEER)
                self.assertIsNotNone(contact)
                self.assertTrue(contact.favourite)
                self.assertEqual(bridge.group_paths([contact])[contact.uin], "Боты")
                bridge._running = True
                bridge.active["telegram"] = False
                bridge._reload_roster()
                self.assertIn(contact.uin, {c.uin for c in bridge.roster()})
                self.assertEqual(bridge.status_of(contact.uin), C.STATUS_ONLINE)
                self.assertFalse(bridge.quote_supported(contact.uin))
                self.assertEqual((await bridge.chat_info(contact.uin))["network"], "Яндекс Go")
                self.assertEqual(await bridge.on_phone_message(contact.uin, "откуда Москва"), -1)
                await asyncio.gather(*bridge._background)
                self.assertIn("Сначала войдите", delivered[-1][1])
                self.assertTrue(delivered[-1][2]["forced"])
                self.assertEqual(backend.calls, ["auth"])
                await bridge._taxi_reply("Машина ждёт")
                self.assertEqual(delivered[-1][1], "Машина ждёт")
            finally:
                await bridge.close()
            self.assertTrue(backend.closed)

    async def test_disabled_does_not_create_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = Bridge(Config(db=str(Path(directory) / "db"), photos_enabled=False,
                                   tg_api_id=1, tg_api_hash="x", tg_session=str(Path(directory) / "tg.session"),
                                   render_enabled=False))
            try:
                self.assertIsNone(bridge.taxi)
                await bridge._apply_roster({})
                self.assertIsNone(bridge.storage.contact_by_peer(TAXI_PEER))
            finally:
                await bridge.close()


if __name__ == "__main__":
    unittest.main()
