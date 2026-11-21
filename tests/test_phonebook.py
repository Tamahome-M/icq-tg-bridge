"""Номера из диалогов и адресных книг сетей, видимые текущей учётке."""
import asyncio
import json
import pathlib
import subprocess
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import playwright
from telethon import functions, types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from bridge.bridge import Bridge
from bridge.express.web import JS_HELPERS, JS_PHONEBOOK
from bridge.max.client import MaxSide
from bridge.phonebook import directory
from bridge.tg.client import TelegramSide


class PhonebookTest(unittest.IsolatedAsyncioTestCase):
    async def test_sources_and_visibility(self):
        tg = TelegramSide.__new__(TelegramSide)
        tg._dialog_phones = {1: ("Друг из чата", "7123"), 2: ("Скрытый номер", "7999")}
        tg.client = AsyncMock(return_value=NS(users=[
            types.User(2, first_name="Скрытый номер"),
            types.User(3, first_name="Друг без чата", phone="7456"),
            types.User(4, is_self=True, phone="7000"), types.UserEmpty(5)]))
        mx = MaxSide.__new__(MaxSide)
        mx.cfg = NS(max_contacts=False)  # the roster limit does not hide phonebook contacts
        mx.me_id = 10
        mx._dialog_phones = {11: ("Друг из чата", "+7123")}
        mx.client = NS(contacts=[NS(id=12, names=[NS(name="Друг MAX")], phone=7789)])
        bridge = Bridge.__new__(Bridge)
        bridge.active = {"telegram": True, "max": True}
        bridge._running = False
        bridge.telegram, bridge.max, bridge.express = tg, mx, None
        entries, partial = await bridge.phonebook()
        self.assertEqual(entries, [("Друг MAX", "+7789"), ("Друг без чата", "+7456"),
                                   ("Друг из чата", "+7123")])
        self.assertFalse(partial)
        tg.client.assert_awaited_once()
        self.assertIsInstance(tg.client.await_args.args[0], functions.contacts.GetContactsRequest)
        bridge.active["telegram"] = False
        self.assertEqual(await bridge.phonebook(),
                         ([("Друг MAX", "+7789"), ("Друг из чата", "+7123")], False))
        tg.client.assert_awaited_once()

    async def test_unavailable_network(self):
        tg = TelegramSide.__new__(TelegramSide)
        tg._dialog_phones = {1: ("Контакт", "+7123")}
        tg.client = AsyncMock(side_effect=asyncio.TimeoutError())
        bridge = Bridge.__new__(Bridge)
        bridge.active, bridge._running = {"telegram": True}, False
        bridge.telegram, bridge.max, bridge.express = tg, None, None
        with self.assertLogs("bridge", level="WARNING"):
            self.assertEqual(await bridge.phonebook(), ([("Контакт", "+7123")], True))

    def test_express_visible_numbers(self):
        node = pathlib.Path(playwright.__file__).parent / "driver/node"
        script = """
            const assert = require('assert'), fs = require('fs');
            const [helpers, phonebook] = JSON.parse(fs.readFileSync(0, 'utf8'));
            const state = {profiles: {
                me: {phonebookProfile: {name: 'Self', contactType: 'phone', contact: '+100'}},
                peer: {ctsProfile: {name: 'Office', phone: '+1 (555) 123, 1234', otherPhone: '2345',
                                    ipPhone: 'sip:example'}},
                saved: {phonebookProfile: {name: 'Saved', contactType: 'phone', contact: '+1555000'}},
                hidden: {ctsProfile: {name:'Group member', phone:'+1999'}},
                email: {phonebookProfile: {contactType: 'email', contact: 'user@example.org'}},
                birthday: {phonebookProfile: {contactType: 'bday', contact: '1990-01-01'}}
            }, indexes: {visibleChats: ['one']}, chats: [
                {groupChatId:'one', chatType:'chat', opponent:{userHuid:'peer'}}
            ]};
            global.window = {__store: {getState: () => state}};
            eval('(' + helpers + ')')();
            assert.deepStrictEqual(eval('(' + phonebook + ')')('me'), [
                ['Office','+1 (555) 123'], ['Office','1234'], ['Office','2345'], ['Saved','+1555000']
            ]);
        """
        subprocess.run([str(node), "-e", script], input=json.dumps([JS_HELPERS, JS_PHONEBOOK]),
                       text=True, check=True)

    def test_numbers(self):
        self.assertEqual(directory([("А", "+7 (123) 45-67"), ("А", "+71234567"),
                                    ("Б", "12#"), ("Б", "++1"), ("В", ""),
                                    ("Другой контакт", "+71234567"), ("А", "+9")]),
                         [("А", "+71234567"), ("А", "+9"), ("Другой контакт", "+71234567")])


if __name__ == "__main__":
    unittest.main()
