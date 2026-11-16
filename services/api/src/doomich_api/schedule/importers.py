"""Импорт расписания из разных источников в единый формат.

* Excel/CSV по шаблону (конкретные даты или день недели + чётность + период);
* iCalendar (.ics) с повторяющимися событиями;
* JSON-API с настраиваемым сопоставлением полей;
* HTML-страница сайта вуза — заготовка, которую дорабатывают под конкретный сайт.

Каждый импортёр возвращает :class:`ImportResult` — события и построчные ошибки.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

WEEKDAYS = {
    "пн": 0,
    "понедельник": 0,
    "mon": 0,
    "monday": 0,
    "вт": 1,
    "вторник": 1,
    "tue": 1,
    "tuesday": 1,
    "ср": 2,
    "среда": 2,
    "wed": 2,
    "wednesday": 2,
    "чт": 3,
    "четверг": 3,
    "thu": 3,
    "thursday": 3,
    "пт": 4,
    "пятница": 4,
    "fri": 4,
    "friday": 4,
    "сб": 5,
    "суббота": 5,
    "sat": 5,
    "saturday": 5,
    "вс": 6,
    "воскресенье": 6,
    "sun": 6,
    "sunday": 6,
}

# Колонки шаблона Excel/CSV: «русское имя» → поле
TEMPLATE_COLUMNS = {
    "группа": "group",
    "дата": "date",
    "день недели": "weekday",
    "неделя": "parity",
    "начало периода": "period_start",
    "конец периода": "period_end",
    "начало": "start",
    "конец": "end",
    "дисциплина": "subject",
    "тип": "kind",
    "аудитория": "room",
    "корпус": "building",
    "преподаватель": "teacher",
    "подгруппа": "subgroup",
    "примечание": "note",
}
TEMPLATE_HEADER = list(TEMPLATE_COLUMNS)


@dataclass
class EventDraft:
    group: str
    starts_at: datetime
    ends_at: datetime
    subject: str
    kind: str | None = None
    room: str | None = None
    building: str | None = None
    teacher: str | None = None
    subgroup: str | None = None
    note: str | None = None
    uid: str = ""

    def __post_init__(self) -> None:
        if not self.uid:
            key = f"{self.group}|{self.starts_at.isoformat()}|{self.subject}|{self.subgroup or ''}"
            self.uid = hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:24]

    def comparable(self) -> dict[str, Any]:
        return {
            "starts_at": self.starts_at.isoformat(),
            "ends_at": self.ends_at.isoformat(),
            "subject": self.subject,
            "kind": self.kind,
            "room": self.room,
            "building": self.building,
            "teacher": self.teacher,
            "subgroup": self.subgroup,
            "note": self.note,
        }


@dataclass
class ImportResult:
    events: list[EventDraft] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def groups(self) -> set[str]:
        return {e.group for e in self.events}

    def content_hash(self) -> str:
        payload = json.dumps(sorted((e.group, e.uid, json.dumps(e.comparable(), sort_keys=True)) for e in self.events))
        return hashlib.sha256(payload.encode()).hexdigest()


class ImportErrorFatal(ValueError):
    pass


# ---------------------------------------------------------------- разбор значений
def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"не удалось разобрать дату «{text}»")


def _parse_time(value: Any) -> time:
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    text = str(value).strip().replace(".", ":")
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", text)
    if not match:
        raise ValueError(f"не удалось разобрать время «{text}»")
    return time(int(match.group(1)), int(match.group(2)))


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parity(value: Any) -> str | None:
    text = (_clean(value) or "").lower()
    if not text or text in {"каждая", "все", "every", "all"}:
        return None
    if text.startswith(("чет", "чёт", "even", "2")):
        return "even"
    if text.startswith(("нечет", "нечёт", "odd", "1")):
        return "odd"
    raise ValueError(f"неизвестная чётность недели «{value}»")


def week_parity(day: date, semester_start: date) -> str:
    """Неделя начала семестра — нечётная (первая)."""
    monday0 = semester_start - timedelta(days=semester_start.weekday())
    monday = day - timedelta(days=day.weekday())
    number = (monday - monday0).days // 7 + 1
    return "odd" if number % 2 else "even"


# ---------------------------------------------------------------- Excel / CSV
def rows_to_events(
    rows: list[dict[str, Any]], tz: ZoneInfo, *, keep_teacher: bool, semester_start: date | None = None
) -> ImportResult:
    result = ImportResult()
    for number, raw in enumerate(rows, start=2):  # строка 1 — заголовок
        row = {TEMPLATE_COLUMNS.get(str(k).strip().lower(), str(k).strip().lower()): v for k, v in raw.items()}
        if not any(_clean(v) for v in row.values()):
            continue
        try:
            group = _clean(row.get("group"))
            subject = _clean(row.get("subject"))
            if not group:
                raise ValueError("не указана группа")
            if not subject:
                raise ValueError("не указана дисциплина")
            start_t, end_t = _parse_time(row.get("start")), _parse_time(row.get("end"))
            if end_t <= start_t:
                raise ValueError("время окончания раньше начала")
            if _clean(row.get("date")):
                days = [_parse_date(row["date"])]
            else:
                weekday_raw = (_clean(row.get("weekday")) or "").lower()
                if weekday_raw not in WEEKDAYS:
                    raise ValueError("укажите дату или день недели")
                period_start = _parse_date(row.get("period_start"))
                period_end = _parse_date(row.get("period_end"))
                if period_end < period_start:
                    raise ValueError("конец периода раньше начала")
                parity = _parity(row.get("parity"))
                anchor = semester_start or period_start
                days = []
                day = period_start + timedelta(days=(WEEKDAYS[weekday_raw] - period_start.weekday()) % 7)
                while day <= period_end:
                    if parity is None or week_parity(day, anchor) == parity:
                        days.append(day)
                    day += timedelta(days=7)
            for day in days:
                result.events.append(
                    EventDraft(
                        group=group,
                        starts_at=datetime.combine(day, start_t, tz),
                        ends_at=datetime.combine(day, end_t, tz),
                        subject=subject,
                        kind=_clean(row.get("kind")),
                        room=_clean(row.get("room")),
                        building=_clean(row.get("building")),
                        teacher=_clean(row.get("teacher")) if keep_teacher else None,
                        subgroup=_clean(row.get("subgroup")),
                        note=_clean(row.get("note")),
                    )
                )
        except (ValueError, KeyError, TypeError) as exc:
            result.errors.append({"row": number, "error": str(exc)})
    return result


def read_excel(data: bytes) -> list[dict[str, Any]]:
    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    rows = list(sheet.iter_rows(values_only=True))
    workbook.close()
    if not rows:
        return []
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    return [dict(zip(header, r, strict=False)) for r in rows[1:]]


def read_csv(data: bytes) -> list[dict[str, Any]]:
    text = data.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t") if text.strip() else csv.excel
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def template_xlsx() -> bytes:
    """Шаблон Excel для администраторов с двумя строками-примерами."""
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Расписание"
    sheet.append(TEMPLATE_HEADER)
    sheet.append(
        [
            "ИВТ-21-1",
            "2027-02-09",
            "",
            "",
            "",
            "",
            "09:00",
            "10:30",
            "Математический анализ",
            "лекция",
            "305",
            "А",
            "",
            "",
            "",
        ]
    )
    sheet.append(
        [
            "ИВТ-21-1",
            "",
            "ср",
            "нечётная",
            "2027-02-08",
            "2027-05-31",
            "10:40",
            "12:10",
            "Программирование",
            "практика",
            "214",
            "Б",
            "",
            "1",
            "",
        ]
    )
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 16
    buf = io.BytesIO()
    workbook.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- iCalendar
def ics_to_events(
    data: bytes, tz: ZoneInfo, *, group: str, window: tuple[date, date], keep_teacher: bool
) -> ImportResult:
    import icalendar
    import recurring_ical_events

    result = ImportResult()
    try:
        calendar = icalendar.Calendar.from_ical(data)
    except ValueError as exc:
        raise ImportErrorFatal(f"Некорректный iCalendar: {exc}") from exc
    for component in recurring_ical_events.of(calendar).between(window[0], window[1] + timedelta(days=1)):
        try:
            start = component.decoded("DTSTART")
            end = component.decoded("DTEND") if "DTEND" in component else start + timedelta(minutes=90)
            if not isinstance(start, datetime):
                continue  # события на весь день — не пары
            start = start if start.tzinfo else start.replace(tzinfo=tz)
            end = end if end.tzinfo else end.replace(tzinfo=tz)
            location = str(component.get("LOCATION", "") or "").strip() or None
            uid = str(component.get("UID", "")) + "|" + start.isoformat()
            result.events.append(
                EventDraft(
                    group=group,
                    starts_at=start,
                    ends_at=end,
                    subject=str(component.get("SUMMARY", "Занятие")).strip(),
                    room=location,
                    teacher=(str(component.get("ORGANIZER", "")).removeprefix("mailto:") or None)
                    if keep_teacher
                    else None,
                    note=(str(component.get("DESCRIPTION", "")).strip()[:500] or None),
                    uid=hashlib.sha1(uid.encode(), usedforsecurity=False).hexdigest()[:24],
                )
            )
        except (KeyError, ValueError) as exc:
            result.errors.append({"row": None, "error": f"событие пропущено: {exc}"})
    return result


# ---------------------------------------------------------------- JSON-адаптер
def _dig(obj: Any, path: str) -> Any:
    """Достать значение по пути «a.b.0.c»."""
    for part in [p for p in path.split(".") if p]:
        if isinstance(obj, list):
            obj = obj[int(part)] if part.isdigit() and int(part) < len(obj) else None
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


def json_to_events(payload: Any, tz: ZoneInfo, config: dict[str, Any], *, keep_teacher: bool) -> ImportResult:
    """Конфигурация::

        {"items": "data.lessons",
         "fields": {"group": "group.name", "date": "date", "start": "time_start", "end": "time_end",
                    "subject": "discipline", "room": "auditorium", "teacher": "teacher.name",
                    "kind": "type", "starts_at": "", "ends_at": ""}}

    Можно задать либо ``starts_at``/``ends_at`` (ISO 8601), либо ``date`` + ``start``/``end``.
    """
    items = _dig(payload, config.get("items", "")) if config.get("items") else payload
    if not isinstance(items, list):
        raise ImportErrorFatal("По пути items не найден список занятий")
    fields = config.get("fields", {})
    result = ImportResult()
    for index, item in enumerate(items):
        try:

            def get(name: str, *, _item=item) -> Any:
                path = fields.get(name)
                return _dig(_item, path) if path else None

            group = _clean(get("group")) or _clean(config.get("group"))
            subject = _clean(get("subject"))
            if not group or not subject:
                raise ValueError("нет группы или дисциплины")
            if get("starts_at"):
                start = datetime.fromisoformat(str(get("starts_at")))
                end = datetime.fromisoformat(str(get("ends_at")))
                start = start if start.tzinfo else start.replace(tzinfo=tz)
                end = end if end.tzinfo else end.replace(tzinfo=tz)
            else:
                day = _parse_date(get("date"))
                start = datetime.combine(day, _parse_time(get("start")), tz)
                end = datetime.combine(day, _parse_time(get("end")), tz)
            result.events.append(
                EventDraft(
                    group=group,
                    starts_at=start,
                    ends_at=end,
                    subject=subject,
                    kind=_clean(get("kind")),
                    room=_clean(get("room")),
                    building=_clean(get("building")),
                    teacher=_clean(get("teacher")) if keep_teacher else None,
                    subgroup=_clean(get("subgroup")),
                    note=_clean(get("note")),
                )
            )
        except (ValueError, TypeError) as exc:
            result.errors.append({"row": index, "error": str(exc)})
    return result


# ---------------------------------------------------------------- HTML (заготовка)
def html_table_to_events(html: str, tz: ZoneInfo, config: dict[str, Any], *, keep_teacher: bool) -> ImportResult:
    """Заготовка парсера страницы расписания.

    Подходит для сайтов, где расписание — HTML-таблица. Конфигурация::

        {"row_selector": "table.schedule tr", "cell_selector": "td",
         "columns": ["date", "start", "end", "subject", "room", "teacher"],
         "group": "ИВТ-21-1"}

    Для сложных сайтов скопируйте функцию в отдельный адаптер и допишите разбор.
    """
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    columns = config.get("columns", [])
    rows = []
    for node in tree.css(config.get("row_selector", "table tr")):
        cells = [c.text(strip=True) for c in node.css(config.get("cell_selector", "td"))]
        if len(cells) < len(columns) or not any(cells):
            continue
        row = dict(zip(columns, cells, strict=False))
        row.setdefault("group", config.get("group"))
        rows.append({k: v for k, v in row.items()})
    # переиспользуем разбор Excel: имена колонок уже служебные
    return rows_to_events(rows, tz, keep_teacher=keep_teacher)
