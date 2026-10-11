"""Данные, которые можно показать в чате, без токенов браузера."""

from __future__ import annotations

from dataclasses import dataclass


class TaxiError(Exception):
    pass


class LoginRequired(TaxiError):
    def __init__(self):
        super().__init__("Сначала войдите в Яндекс Go на сервере: ./run.py login taxi. "
                         "Затем напишите сюда «поездка». Номер и код вводятся на сервере.")


class NotSubmitted(TaxiError):
    """Браузер достоверно не запускал действие заказа/отмены."""


class OutcomeUnknown(TaxiError):
    def __init__(self, order_id: str = ""):
        super().__init__("Ответ на заказ не получен. Повторный заказ заблокирован; "
                         "напишите «статус» и проверьте поездки в Яндекс Go.")
        self.order_id = order_id


TERMINAL = frozenset({"complete", "failed", "cancelled", "expired", "preexpired"})
STATUS_TEXT = {
    "draft": "Заказ оформляется", "search": "Ищем машину",
    "scheduling": "Оформляем поездку ко времени", "scheduled": "Поездка запланирована",
    "driving": "Машина едет к вам", "waiting": "Машина ждёт вас",
    "calling": "Водитель связывается с вами", "boarding": "Посадка",
    "transporting": "Поездка началась", "complete": "Поездка завершена",
    "cancelled": "Поездка отменена", "expired": "Машина не найдена",
    "preexpired": "Запланированная поездка не состоялась", "failed": "Заказ не удался",
}


@dataclass(frozen=True)
class Fare:
    code: str
    title: str
    price: str


@dataclass(frozen=True)
class Quote:
    origin: str
    destination: str
    fares: tuple[Fare, ...]
    selected: str
    payment: str
    # stable связывает подтверждение с маршрутом, ценой, оплатой и аккаунтом.
    # guard дополнительно включает предложение сервера: проверяется в JS
    # непосредственно перед штатным обработчиком кнопки заказа.
    stable: str
    guard: str

    @property
    def fare(self) -> Fare:
        return next(f for f in self.fares if f.code == self.selected)

    def text(self) -> str:
        return (f"Откуда: {self.origin}\nКуда: {self.destination}\n"
                f"Тариф: {self.fare.title}\nСтоимость по сайту: {self.fare.price}\n"
                f"Оплата: {self.payment}")


@dataclass(frozen=True)
class Trip:
    order_id: str
    status: str
    car: str = ""
    number: str = ""
    driver: str = ""
    phone: str = ""
    cancel_state: str = ""
    price: str = ""

    @property
    def finished(self) -> bool:
        return self.status in TERMINAL

    @property
    def notification_key(self) -> tuple:
        return (self.order_id, self.status, self.car, self.number, self.driver, self.price)

    def text(self) -> str:
        lines = [STATUS_TEXT.get(self.status, f"Статус заказа: {self.status}")]
        if self.car:
            lines.append(self.car)
        if self.number:
            lines.append(f"Номер: {self.number}")
        if self.driver:
            lines.append(f"Водитель: {self.driver}")
        if self.phone:
            lines.append(f"Телефон: {self.phone}")
        if self.price:
            lines.append(f"Стоимость: {self.price}")
        return "\n".join(lines)


@dataclass(frozen=True)
class ExtraConfirmation:
    """Штатное окно сайта до отправки заказа: условия надо показать пользователю."""
    text: str
