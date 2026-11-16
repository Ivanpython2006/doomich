from __future__ import annotations

from datetime import date, datetime, timedelta

from doomich_api.ai.llm import LlmEvent, ToolCall
from sqlalchemy import select, text

from tests.conftest import parse_sse, register


async def _seed_schedule(tenant):
    from doomich_api.db import RlsContext, session_scope
    from doomich_api.models import University
    from doomich_api.schedule.importers import EventDraft, ImportResult
    from doomich_api.schedule.service import apply_import, tz_of

    async with session_scope(RlsContext.system()) as session:
        uni = await session.get(University, tenant.university_id)
        tz = tz_of(uni)
        start = datetime.combine(date.today(), datetime.min.time(), tz).replace(hour=9)
        result = ImportResult(
            events=[
                EventDraft(
                    group=tenant.group_code,
                    starts_at=start,
                    ends_at=start + timedelta(minutes=90),
                    subject="Математический анализ",
                    kind="лекция",
                    room="305",
                    building="А",
                    teacher="Иванов И.И.",
                ),
            ]
        )
        await apply_import(session, uni, result)


async def test_chat_with_schedule_tool(client, tenant, providers):
    await _seed_schedule(tenant)
    user = await register(client, tenant)
    chat = (await client.post("/v1/chats", json={}, headers=user["headers"])).json()

    resp = await client.post(
        f"/v1/chats/{chat['id']}/messages", json={"text": "Какое у меня сегодня расписание?"}, headers=user["headers"]
    )
    assert resp.status_code == 200
    events = parse_sse(resp.text)
    names = [e[0] for e in events]
    assert names[0] == "start" and names[-1] == "done"
    assert ("tool", {"name": "get_schedule"}) in events
    done = events[-1][1]
    assert "Математический анализ" in done["text"]
    assert done["message_id"]

    # промпт получил текущую дату и правила
    system = providers.llm.calls[0]["messages"][0]["content"]
    assert "Думыч" in system and "get_schedule" in system

    history = (await client.get(f"/v1/chats/{chat['id']}/messages", headers=user["headers"])).json()
    assert [m["author"] for m in history] == ["user", "assistant"]
    chats = (await client.get("/v1/chats", headers=user["headers"])).json()
    assert chats[0]["title"].startswith("Какое у меня")


async def test_messages_are_encrypted_at_rest(client, tenant, providers):
    user = await register(client, tenant)
    chat = (await client.post("/v1/chats", json={}, headers=user["headers"])).json()
    secret = "секретная фраза про курсовую 42"
    await client.post(f"/v1/chats/{chat['id']}/messages", json={"text": secret}, headers=user["headers"])

    from doomich_api.db import RlsContext, session_scope

    async with session_scope(RlsContext.system()) as session:
        raw = (await session.execute(text("SELECT content_enc FROM messages"))).scalars().all()
    assert raw and all(secret.encode() not in bytes(blob) for blob in raw)


async def test_incognito_is_not_stored(client, tenant, providers):
    user = await register(client, tenant)
    resp = await client.post(
        "/v1/chat/incognito",
        json={
            "text": "Привет!",
            "history": [{"role": "user", "content": "раньше"}, {"role": "assistant", "content": "ответ"}],
        },
        headers=user["headers"],
    )
    events = parse_sse(resp.text)
    assert events[-1][0] == "done" and "message_id" not in events[-1][1]
    assert providers.llm.calls[0]["messages"][1]["content"] == "раньше"
    assert (await client.get("/v1/chats", headers=user["headers"])).json() == []


async def test_isolation_between_users(client, tenant, providers):
    alice = await register(client, tenant)
    bob = await register(client, tenant)
    chat = (await client.post("/v1/chats", json={"title": "Личное"}, headers=alice["headers"])).json()
    await client.post(f"/v1/chats/{chat['id']}/messages", json={"text": "привет"}, headers=alice["headers"])

    assert (await client.get(f"/v1/chats/{chat['id']}/messages", headers=bob["headers"])).status_code == 404
    assert (await client.delete(f"/v1/chats/{chat['id']}", headers=bob["headers"])).status_code == 404
    resp = await client.post(f"/v1/chats/{chat['id']}/messages", json={"text": "взлом"}, headers=bob["headers"])
    assert resp.status_code == 404

    # второй рубеж: политика RLS в PostgreSQL не отдаёт чужие строки даже прямым запросом
    import uuid

    from doomich_api.db import RlsContext, session_scope
    from doomich_api.models import Chat, Message

    bob_ctx = RlsContext(user_id=uuid.UUID(bob["user"]["id"]), university_id=tenant.university_id)
    async with session_scope(bob_ctx) as session:
        assert (await session.execute(select(Chat))).scalars().all() == []
        assert (await session.execute(select(Message))).scalars().all() == []
    alice_ctx = RlsContext(user_id=uuid.UUID(alice["user"]["id"]), university_id=tenant.university_id)
    async with session_scope(alice_ctx) as session:
        assert len((await session.execute(select(Message))).scalars().all()) == 2


async def test_llm_tool_loop_with_scripted_model(client, tenant, providers):
    """Модель вызывает инструмент, получает ответ и пишет итог — проверяем цикл оркестратора."""
    providers.llm.script = [
        [
            LlmEvent("delta", text="Сейчас посмотрю. "),
            LlmEvent("tool_calls", tool_calls=[ToolCall("c1", "get_schedule", '{"date_from": "2000-01-01"}')]),
            LlmEvent("done"),
        ],
        [LlmEvent("delta", text="Пар нет."), LlmEvent("done", model="test-model")],
    ]
    user = await register(client, tenant)
    resp = await client.post("/v1/chat/incognito", json={"text": "что 1 января 2000?"}, headers=user["headers"])
    done = parse_sse(resp.text)[-1][1]
    assert done["text"] == "Сейчас посмотрю. Пар нет."
    assert done["model"] == "test-model"
    tool_message = providers.llm.calls[1]["messages"][-1]
    assert tool_message["role"] == "tool" and "Занятий нет" in tool_message["content"]


async def test_daily_limit(client, tenant, providers, monkeypatch):
    from doomich_api.config import get_settings

    monkeypatch.setattr(get_settings(), "messages_per_day_limit", 1)
    user = await register(client, tenant)
    first = await client.post("/v1/chat/incognito", json={"text": "раз"}, headers=user["headers"])
    assert first.status_code == 200
    second = await client.post("/v1/chat/incognito", json={"text": "два"}, headers=user["headers"])
    assert second.status_code == 429
