"""Нормализация текста перед синтезом речи: числа, время, даты, проценты, сокращения.

Нейросетевые TTS плохо читают «16.11.2026», «09:30», «25%» и «ауд. 305» — переводим их в слова.
"""

from __future__ import annotations

import re

_UNITS_M = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_UNITS_F = ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_TEENS = [
    "десять",
    "одиннадцать",
    "двенадцать",
    "тринадцать",
    "четырнадцать",
    "пятнадцать",
    "шестнадцать",
    "семнадцать",
    "восемнадцать",
    "девятнадцать",
]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
_HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]
_ORDERS = [
    (("", "", ""), False),
    (("тысяча", "тысячи", "тысяч"), True),
    (("миллион", "миллиона", "миллионов"), False),
    (("миллиард", "миллиарда", "миллиардов"), False),
]

_ORD_UNITS_GEN = [
    "",
    "первого",
    "второго",
    "третьего",
    "четвёртого",
    "пятого",
    "шестого",
    "седьмого",
    "восьмого",
    "девятого",
]
_ORD_TEENS_GEN = [
    "десятого",
    "одиннадцатого",
    "двенадцатого",
    "тринадцатого",
    "четырнадцатого",
    "пятнадцатого",
    "шестнадцатого",
    "семнадцатого",
    "восемнадцатого",
    "девятнадцатого",
]
_ORD_TENS_GEN = [
    "",
    "",
    "двадцатого",
    "тридцатого",
    "сорокового",
    "пятидесятого",
    "шестидесятого",
    "семидесятого",
    "восьмидесятого",
    "девяностого",
]
_DAY_ORD = [
    "",
    "первое",
    "второе",
    "третье",
    "четвёртое",
    "пятое",
    "шестое",
    "седьмое",
    "восьмое",
    "девятое",
    "десятое",
    "одиннадцатое",
    "двенадцатое",
    "тринадцатое",
    "четырнадцатое",
    "пятнадцатое",
    "шестнадцатое",
    "семнадцатое",
    "восемнадцатое",
    "девятнадцатое",
    "двадцатое",
    "двадцать первое",
    "двадцать второе",
    "двадцать третье",
    "двадцать четвёртое",
    "двадцать пятое",
    "двадцать шестое",
    "двадцать седьмое",
    "двадцать восьмое",
    "двадцать девятое",
    "тридцатое",
    "тридцать первое",
]
_MONTHS_GEN = [
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]
_ABBREVIATIONS = {
    r"\bт\.\s?е\.": "то есть",
    r"\bт\.\s?к\.": "так как",
    r"\bт\.\s?д\.": "так далее",
    r"\bт\.\s?п\.": "тому подобное",
    r"\bи\s?др\.": "и другие",
    r"\bауд\.": "аудитория",
    r"\bкорп\.": "корпус",
    r"\bстр\.": "страница",
    r"\bим\.": "имени",
    r"\bпреп\.": "преподаватель",
    r"\bкаф\.": "кафедра",
    r"\bмин\.": "минут",
    "№": "номер ",
}


def plural(n: int, forms: tuple[str, str, str]) -> str:
    n = abs(n)
    if 11 <= n % 100 <= 14:
        return forms[2]
    if n % 10 == 1:
        return forms[0]
    if 2 <= n % 10 <= 4:
        return forms[1]
    return forms[2]


def _triad(n: int, feminine: bool) -> list[str]:
    words = [_HUNDREDS[n // 100]]
    rest = n % 100
    if 10 <= rest < 20:
        words.append(_TEENS[rest - 10])
    else:
        words.append(_TENS[rest // 10])
        words.append((_UNITS_F if feminine else _UNITS_M)[rest % 10])
    return [w for w in words if w]


def number_ru(n: int, *, feminine: bool = False) -> str:
    """Количественное числительное: 2026 → «две тысячи двадцать шесть»."""
    if n == 0:
        return "ноль"
    if n < 0:
        return "минус " + number_ru(-n, feminine=feminine)
    words: list[str] = []
    for order, ((one, few, many), fem) in reversed(list(enumerate(_ORDERS))):
        value = (n // 1000**order) % 1000
        if value == 0:
            continue
        words += _triad(value, feminine if order == 0 else fem)
        if order:
            words.append(plural(value, (one, few, many)))
    return " ".join(words)


def year_genitive_ru(year: int) -> str:
    """Порядковое в родительном падеже: 2026 → «две тысячи двадцать шестого»."""
    if year % 1000 == 0 and year <= 3000:
        return {1000: "тысячного", 2000: "двухтысячного", 3000: "трёхтысячного"}[year]
    rest = year % 100
    if rest == 0:
        hundreds = (year % 1000) // 100
        prefix = number_ru(year - year % 1000) if year >= 1000 else ""
        ordinal = {
            1: "сотого",
            2: "двухсотого",
            3: "трёхсотого",
            4: "четырёхсотого",
            5: "пятисотого",
            6: "шестисотого",
            7: "семисотого",
            8: "восьмисотого",
            9: "девятисотого",
        }[hundreds]
        return f"{prefix} {ordinal}".strip()
    if rest < 10:
        last, base = _ORD_UNITS_GEN[rest], year - rest
    elif rest < 20:
        last, base = _ORD_TEENS_GEN[rest - 10], year - rest
    elif rest % 10 == 0:
        last, base = _ORD_TENS_GEN[rest // 10], year - rest
    else:
        last, base = _ORD_UNITS_GEN[rest % 10], year - rest % 10
    prefix = number_ru(base) if base else ""
    return f"{prefix} {last}".strip()


_EN_SMALL = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def number_en(n: int) -> str:
    if n < 0:
        return "minus " + number_en(-n)
    if n < 20:
        return _EN_SMALL[n]
    if n < 100:
        return _EN_TENS[n // 10] + ("" if n % 10 == 0 else "-" + _EN_SMALL[n % 10])
    if n < 1000:
        return _EN_SMALL[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + number_en(n % 100))
    for value, name in ((10**9, "billion"), (10**6, "million"), (1000, "thousand")):
        if n >= value:
            head, tail = divmod(n, value)
            return number_en(head) + f" {name}" + ("" if tail == 0 else " " + number_en(tail))
    return str(n)


def normalize(text: str, language: str = "ru") -> str:
    if language.startswith("en"):
        return _normalize_en(text)
    for pattern, replacement in _ABBREVIATIONS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    def date(match: re.Match[str]) -> str:
        day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
        if not (1 <= day <= 31 and 1 <= month <= 12):
            return match.group(0)
        out = f"{_DAY_ORD[day]} {_MONTHS_GEN[month]}"
        if year:
            y = int(year) if len(year) == 4 else 2000 + int(year)
            out += f" {year_genitive_ru(y)} года"
        return out

    text = re.sub(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}|\d{2}))?\b", date, text)

    def clock(match: re.Match[str]) -> str:
        hours, minutes = int(match.group(1)), int(match.group(2))
        if hours > 23 or minutes > 59:
            return match.group(0)
        tail = "ноль ноль" if minutes == 0 else ("ноль " + number_ru(minutes) if minutes < 10 else number_ru(minutes))
        return f"{number_ru(hours)} {tail}"

    text = re.sub(r"\b(\d{1,2}):(\d{2})\b", clock, text)

    def percent(match: re.Match[str]) -> str:
        n = int(match.group(1))
        return f"{number_ru(n)} {plural(n, ('процент', 'процента', 'процентов'))}"

    text = re.sub(r"(\d+)\s?%", percent, text)

    def decimal(match: re.Match[str]) -> str:
        whole, frac = match.group(1), match.group(2)
        # «2,05» читаем по цифрам после нуля, «2,5» — числом
        tail = " ".join(number_ru(int(d)) for d in frac) if frac.startswith("0") else number_ru(int(frac))
        return f"{number_ru(int(whole))} запятая {tail}"

    text = re.sub(r"\b(\d+)[,.](\d+)\b", decimal, text)
    text = re.sub(r"\d+", lambda m: number_ru(int(m.group(0))) if len(m.group(0)) <= 12 else m.group(0), text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_en(text: str) -> str:
    def clock(match: re.Match[str]) -> str:
        minutes = match.group(2)
        tail = "o'clock" if minutes == "00" else number_en(int(minutes))
        return f"{number_en(int(match.group(1)))} {tail}"

    text = re.sub(r"\b(\d{1,2}):(\d{2})\b", clock, text)
    text = re.sub(r"(\d+)\s?%", lambda m: f"{number_en(int(m.group(1)))} percent", text)
    text = re.sub(r"\d+", lambda m: number_en(int(m.group(0))) if len(m.group(0)) <= 12 else m.group(0), text)
    return re.sub(r"\s+", " ", text).strip()
