"""Locale-aware desktop formatting helpers."""

from __future__ import annotations

from datetime import date

from attentionos.localization import Translator

RU_MONTHS = {
    1: ("января", "янв."),
    2: ("февраля", "февр."),
    3: ("марта", "мар."),
    4: ("апреля", "апр."),
    5: ("мая", "мая"),
    6: ("июня", "июн."),
    7: ("июля", "июл."),
    8: ("августа", "авг."),
    9: ("сентября", "сент."),
    10: ("октября", "окт."),
    11: ("ноября", "нояб."),
    12: ("декабря", "дек."),
}

RU_WEEKDAYS = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}


def format_duration(seconds: float, translator: Translator | None = None) -> str:
    """Format a duration for compact dashboard metrics."""
    if translator is None:
        if seconds <= 0:
            return "0m"
        minutes = int(round(seconds / 60))
        if minutes < 60:
            return f"{minutes}m"
        hours, rest = divmod(minutes, 60)
        return f"{hours}h" if rest == 0 else f"{hours}h {rest}m"

    if seconds <= 0:
        return translator.t("duration.zero")
    if seconds < 60:
        return translator.t("duration.sec", count=max(int(round(seconds)), 1))
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return translator.t("duration.min", count=minutes)
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return translator.t("duration.hour", count=hours)
    return translator.t("duration.hour_min", hours=hours, minutes=rest)


def format_long_date(value: date, translator: Translator) -> str:
    """Format dashboard date according to selected language."""
    if translator.language == "ru":
        month = RU_MONTHS[value.month][0]
        weekday = RU_WEEKDAYS[value.weekday()]
        return f"{weekday}, {value.day} {month} {value.year}"
    return value.strftime("%A, %B %d, %Y")


def format_short_date(value: date, translator: Translator) -> str:
    """Format timeline navigation date according to selected language."""
    if translator.language == "ru":
        return f"{value.day} {RU_MONTHS[value.month][1]}"
    return value.strftime("%b %d")
