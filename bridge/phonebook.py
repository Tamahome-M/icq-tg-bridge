"""Номера, которые сети раскрывают текущему аккаунту."""
import re


def phone_number(value, *, international=False) -> str:
    if not value:
        return ""
    number = re.sub(r"[ ().-]", "", str(value))
    if re.fullmatch(r"\+?[0-9]{1,32}", number):
        return "+" + number.lstrip("+") if international else number
    return ""


def international_number(value) -> str:
    return phone_number(value, international=True)


def directory(rows):
    entries = set()
    for name, value in rows:
        number = phone_number(value)
        if number:
            name = " ".join((name or "").split())[:100]
            entries.add((name or number, number))
    return sorted(entries, key=lambda row: (row[0].casefold(), row[0], row[1]))
