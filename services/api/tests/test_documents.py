from __future__ import annotations

import uuid

from sqlalchemy import func, select

from tests.conftest import parse_sse, register
from tests.helpers_files import make_docx, make_pdf, make_xlsx


async def _upload(client, user, name: str, data: bytes):
    return await client.post("/v1/documents", files={"file": (name, data)}, headers=user["headers"])


async def test_upload_docx_and_answer_with_citations(client, tenant, providers):
    user = await register(client, tenant)
    data = make_docx(
        [
            ("Законы Ньютона", "h1"),
            (
                "Первый закон Ньютона: тело сохраняет состояние покоя или равномерного движения, "
                "пока на него не действуют другие тела.",
                None,
            ),
            ("Термодинамика", "h1"),
            ("Энтропия изолированной системы не убывает.", None),
        ]
    )
    resp = await _upload(client, user, "физика.docx", data)
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert doc["status"] == "ready", doc
    assert doc["title"] == "физика.docx"

    chat = (await client.post("/v1/chats", json={"document_ids": [doc["id"]]}, headers=user["headers"])).json()
    resp = await client.post(
        f"/v1/chats/{chat['id']}/messages",
        json={"text": "Что говорит первый закон Ньютона?"},
        headers=user["headers"],
    )
    events = parse_sse(resp.text)
    assert ("tool", {"name": "search_documents"}) in events
    done = events[-1][1]
    assert done["citations"], done
    citation = done["citations"][0]
    assert citation["title"] == "физика.docx"
    assert "Ньютона" in citation["snippet"]

    chunk = await client.get(f"/v1/documents/{doc['id']}/chunks/{citation['chunk_id']}", headers=user["headers"])
    assert chunk.status_code == 200 and "Ньютона" in chunk.json()["body"]


async def test_xlsx_and_pdf_parsing(client, tenant, providers):
    user = await register(client, tenant)
    xlsx = make_xlsx([["Опыт", "Температура", "Давление"], ["1", "20", "101"], ["2", "35", "120"]])
    pdf = make_pdf(["Laboratory work 3", "Ohm law: U = I * R", "Resistance grows with temperature"])
    r1 = (await _upload(client, user, "lab.xlsx", xlsx)).json()
    r2 = (await _upload(client, user, "ohm.pdf", pdf)).json()
    assert r1["status"] == "ready" and r1["pages"] == 1
    assert r2["status"] == "ready" and r2["pages"] == 1

    from doomich_api.db import RlsContext, session_scope
    from doomich_api.models import Chunk

    async with session_scope(RlsContext.system()) as session:
        bodies = (
            (await session.execute(select(Chunk.body).where(Chunk.document_id == uuid.UUID(r1["id"])))).scalars().all()
        )
    assert any("| Опыт | Температура | Давление |" in b for b in bodies)


async def test_rejects_unsupported_and_isolates_documents(client, tenant, providers):
    alice = await register(client, tenant)
    bob = await register(client, tenant)
    bad = await _upload(client, alice, "virus.exe", b"MZ\x90\x00binary")
    assert bad.status_code == 415

    doc = (await _upload(client, alice, "заметки.md", "# Тема\nСекретные заметки Алисы про интегралы".encode())).json()
    assert (await client.get(f"/v1/documents/{doc['id']}", headers=bob["headers"])).status_code == 404
    assert (await client.delete(f"/v1/documents/{doc['id']}", headers=bob["headers"])).status_code == 404

    # поиск Боба не находит документы Алисы
    resp = await client.post(
        "/v1/chat/incognito", json={"text": "найди в документе про интегралы"}, headers=bob["headers"]
    )
    done = parse_sse(resp.text)[-1][1]
    assert not done["citations"]


async def test_delete_document_removes_chunks(client, tenant, providers):
    user = await register(client, tenant)
    doc = (await _upload(client, user, "a.txt", "Текст про квантовую механику и волновую функцию.".encode())).json()
    resp = await client.delete(f"/v1/documents/{doc['id']}", headers=user["headers"])
    assert resp.status_code == 200

    from doomich_api.db import RlsContext, session_scope
    from doomich_api.models import Chunk

    async with session_scope(RlsContext.system()) as session:
        count = (
            await session.execute(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == uuid.UUID(doc["id"]))
            )
        ).scalar_one()
    assert count == 0


async def test_scanned_pdf_fails_gracefully(client, tenant, providers):
    user = await register(client, tenant)
    doc = (await _upload(client, user, "scan.pdf", make_pdf([]))).json()
    assert doc["status"] == "failed"
    assert "скан" in doc["error"].lower() or "текст" in doc["error"].lower()
