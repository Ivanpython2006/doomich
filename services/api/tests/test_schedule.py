from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from doomich_api.schedule.importers import (
    EventDraft,
    ImportResult,
    ics_to_events,
    json_to_events,
    read_excel,
    rows_to_events,
    template_xlsx,
    week_parity,
)

from tests.conftest import register

TZ = ZoneInfo("Europe/Moscow")


def test_template_roundtrip_and_weekly_expansion():
    rows = read_excel(template_xlsx())
    result = rows_to_events(rows, TZ, keep_teacher=False, semester_start=date(2027, 2, 8))
    assert not result.errors
    one_off = [e for e in result.events if e.subject == "Математический анализ"]
    weekly = [e for e in result.events if e.subject == "Программирование"]
    assert len(one_off) == 1 and one_off[0].starts_at == datetime(2027, 2, 9, 9, 0, tzinfo=TZ)
    # среды нечётных недель с 8 февраля по 31 мая
    assert all(e.starts_at.weekday() == 2 for e in weekly)
    assert all(week_parity(e.starts_at.date(), date(2027, 2, 8)) == "odd" for e in weekly)
    assert len(weekly) == 8


def test_row_errors_are_reported():
    rows = [
        {"Группа": "А-1", "Дата": "2027-02-10", "Начало": "10:00", "Конец": "09:00", "Дисциплина": "Химия"},
        {"Группа": "", "Дата": "2027-02-10", "Начало": "10:00", "Конец": "11:00", "Дисциплина": "Химия"},
        {
            "Группа": "А-1",
            "Дата": "10.02.2027",
            "Начало": "10.00",
            "Конец": "11:30",
            "Дисциплина": "Химия",
            "Преподаватель": "Петрова А.А.",
        },
    ]
    result = rows_to_events(rows, TZ, keep_teacher=False)
    assert [e["row"] for e in result.errors] == [2, 3]
    assert len(result.events) == 1 and result.events[0].teacher is None  # ФИО не сохраняем без разрешения вуза


def test_ics_with_recurrence():
    ics = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:test\nBEGIN:VEVENT\nUID:lesson-1\n"
        "DTSTART;TZID=Europe/Moscow:20270208T090000\nDTEND;TZID=Europe/Moscow:20270208T103000\n"
        "RRULE:FREQ=WEEKLY;COUNT=4\nSUMMARY:Алгебра\nLOCATION:214\nEND:VEVENT\nEND:VCALENDAR\n"
    ).encode()
    result = ics_to_events(ics, TZ, group="Б-2", window=(date(2027, 2, 1), date(2027, 3, 31)), keep_teacher=False)
    assert len(result.events) == 4
    assert {e.room for e in result.events} == {"214"}
    assert len({e.uid for e in result.events}) == 4


def test_json_adapter():
    payload = {
        "data": {
            "lessons": [
                {
                    "grp": {"name": "В-3"},
                    "day": "2027-03-01",
                    "from": "12:40",
                    "to": "14:10",
                    "title": "Физика",
                    "aud": "101",
                },
                {"grp": {"name": "В-3"}, "day": "bad", "from": "12:40", "to": "14:10", "title": "Физика"},
            ]
        }
    }
    config = {
        "items": "data.lessons",
        "fields": {"group": "grp.name", "date": "day", "start": "from", "end": "to", "subject": "title", "room": "aud"},
    }
    result = json_to_events(json.loads(json.dumps(payload)), TZ, config, keep_teacher=False)
    assert len(result.events) == 1 and result.events[0].room == "101"
    assert result.errors[0]["row"] == 1


async def test_apply_import_diff_and_api(client, tenant):
    from doomich_api.db import RlsContext, session_scope
    from doomich_api.models import University
    from doomich_api.schedule.service import apply_import

    today = date.today()
    base = datetime.combine(today, datetime.min.time(), TZ)

    def drafts(room: str, with_second: bool) -> ImportResult:
        events = [
            EventDraft(
                group=tenant.group_code,
                starts_at=base.replace(hour=9),
                ends_at=base.replace(hour=10, minute=30),
                subject="История",
                room=room,
                teacher="Сидоров С.С.",
            )
        ]
        if with_second:
            events.append(
                EventDraft(
                    group=tenant.group_code,
                    starts_at=base.replace(hour=11),
                    ends_at=base.replace(hour=12),
                    subject="Философия",
                    room="100",
                )
            )
        return ImportResult(events=events)

    async with session_scope(RlsContext.system()) as session:
        uni = await session.get(University, tenant.university_id)
        first = await apply_import(session, uni, drafts("101", True))
        second = await apply_import(session, uni, drafts("202", False))
    assert first["added"] == 2
    assert second == {"groups": 1, "added": 0, "removed": 1, "changed": 1, "unchanged": 0, "errors": 0}

    user = await register(client, tenant)
    events = (
        await client.get(
            "/v1/schedule", params={"from": today.isoformat(), "to": today.isoformat()}, headers=user["headers"]
        )
    ).json()
    assert [(e["subject"], e["room"], e["teacher"]) for e in events] == [("История", "202", "Сидоров С.С.")]

    since = (datetime.now(TZ) - timedelta(hours=1)).isoformat()
    changes = (await client.get("/v1/schedule/changes", params={"since": since}, headers=user["headers"])).json()
    assert {c["change"] for c in changes} >= {"added", "changed", "removed"}

    teachers = (await client.get("/v1/teachers", params={"q": "сидор"}, headers=user["headers"])).json()
    assert teachers == ["Сидоров С.С."]
    by_teacher = (
        await client.get(
            "/v1/schedule", params={"teacher": "Сидоров С.С.", "from": today.isoformat()}, headers=user["headers"]
        )
    ).json()
    assert len(by_teacher) == 1
