from __future__ import annotations

import uuid

import pyotp
from doomich_common.registry import Manifest, ModelKind, ModelRegistry

from tests.conftest import parse_sse, register
from tests.helpers_files import make_xlsx


async def _admin_headers(client) -> dict[str, str]:
    from doomich_api.api.admin import create_admin_account
    from doomich_api.db import RlsContext, session_scope

    login = f"root-{uuid.uuid4().hex[:6]}"
    async with session_scope(RlsContext.system()) as session:
        _admin, uri = await create_admin_account(session, login, "очень-длинный-пароль", "superadmin", None)
    secret = pyotp.parse_uri(uri).secret
    bad = await client.post(
        "/admin/v1/auth/login", json={"login": login, "password": "очень-длинный-пароль", "totp": "000000"}
    )
    assert bad.status_code == 401
    resp = await client.post(
        "/admin/v1/auth/login",
        json={"login": login, "password": "очень-длинный-пароль", "totp": pyotp.TOTP(secret).now()},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_admin_full_flow(client, providers, tmp_path):
    headers = await _admin_headers(client)
    slug = f"adm-{uuid.uuid4().hex[:5]}"
    uni = (
        await client.post("/admin/v1/universities", json={"slug": slug, "name": "Админ-вуз"}, headers=headers)
    ).json()
    campus = (
        await client.post(
            f"/admin/v1/universities/{uni['id']}/campuses", json={"slug": "main", "name": "Главный"}, headers=headers
        )
    ).json()
    group = (
        await client.post(f"/admin/v1/universities/{uni['id']}/groups", json={"code": "ПИ-25-2"}, headers=headers)
    ).json()

    # коды приглашения: показываются один раз, в БД только хэши
    batch = (
        await client.post(
            f"/admin/v1/universities/{uni['id']}/invite-batches",
            json={"count": 3, "group_id": group["id"]},
            headers=headers,
        )
    ).json()
    assert len(batch["codes"]) == 3 and batch["codes"][0]["app_link"].startswith("doomich://invite/")
    listing = (await client.get(f"/admin/v1/universities/{uni['id']}/invite-batches", headers=headers)).json()
    assert listing[0]["count"] == 3 and listing[0]["activations"] == 0

    # импорт расписания: предпросмотр, затем применение
    xlsx = make_xlsx(
        [
            ["Группа", "Дата", "Начало", "Конец", "Дисциплина", "Аудитория"],
            ["ПИ-25-2", "2027-02-10", "09:00", "10:30", "Базы данных", "410"],
            ["ПИ-25-2", "2027-02-10", "25:00", "10:30", "Ошибка", "1"],
        ]
    )
    preview = (
        await client.post(
            f"/admin/v1/universities/{uni['id']}/schedule/import",
            files={"file": ("s.xlsx", xlsx)},
            data={"preview": "true"},
            headers=headers,
        )
    ).json()
    assert preview["events"] == 1 and preview["errors"][0]["row"] == 3
    applied = (
        await client.post(
            f"/admin/v1/universities/{uni['id']}/schedule/import",
            files={"file": ("s.xlsx", xlsx)},
            data={"preview": "false"},
            headers=headers,
        )
    ).json()
    assert applied["stats"]["added"] == 1

    # база знаний вуза доступна студентам через university_info
    kb = await client.post(
        f"/admin/v1/universities/{uni['id']}/kb",
        files={"file": ("faq.md", "# Стипендия\nСтипендия выплачивается 25 числа каждого месяца.".encode())},
        headers=headers,
    )
    assert kb.status_code == 201 and kb.json()["status"] == "ready"

    # регистрация студента по коду из админки и вопрос о вузе
    resp = await client.post(
        "/v1/auth/register",
        json={"invite_code": batch["codes"][0]["code"], "login": "Студент77", "password": "очень-надёжный-пароль-1"},
    )
    student = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    from doomich_api.ai.conversation import _flags_cache

    _flags_cache.clear()
    answer = await client.post("/v1/chat/incognito", json={"text": "Когда платят стипендию в вузе?"}, headers=student)
    events = parse_sse(answer.text)
    assert ("tool", {"name": "university_info"}) in events
    assert "25 числа" in events[-1][1]["text"]

    # граф кампуса и маршрут
    graph = {
        "buildings": [
            {
                "slug": "a",
                "name": "Корпус А",
                "floors": [
                    {
                        "level": 1,
                        "meters_per_px": 0.1,
                        "nodes": [
                            {"key": "in", "kind": "entrance", "name": "Главный вход", "x": 0, "y": 0},
                            {"key": "c1", "kind": "corridor", "x": 100, "y": 0},
                            {"key": "st1", "kind": "stairs", "x": 200, "y": 0},
                        ],
                    },
                    {
                        "level": 3,
                        "meters_per_px": 0.1,
                        "nodes": [
                            {"key": "st3", "kind": "stairs", "x": 200, "y": 0},
                            {"key": "r305", "kind": "room", "room": "305", "x": 300, "y": 50},
                        ],
                    },
                ],
            }
        ],
        "edges": [
            {"a": "in", "b": "c1"},
            {"a": "c1", "b": "st1"},
            {"a": "st1", "b": "st3", "kind": "stairs", "length_m": 8, "accessible": False},
            {"a": "st3", "b": "r305"},
        ],
    }
    put = await client.put(f"/admin/v1/campuses/{campus['id']}/graph", json=graph, headers=headers)
    assert put.json() == {"nodes": 5, "edges": 4}
    route = await client.post("/v1/nav/route", json={"origin": "Главный вход", "destination": "305"}, headers=student)
    assert route.status_code == 200, route.text
    steps = route.json()["steps"]
    assert any("Поднимитесь по лестнице на 3 этаж" in s for s in steps)
    assert steps[-1] == "Вы на месте: аудитория 305"
    no_route = await client.post(
        "/v1/nav/route", json={"origin": "Главный вход", "destination": "305", "accessible": True}, headers=student
    )
    assert no_route.status_code == 404

    status = (await client.get("/admin/v1/status", headers=headers)).json()
    assert status["checks"]["database"] == "ok" and status["checks"]["llm"] == "fake"
    audit = (await client.get("/admin/v1/audit", headers=headers)).json()
    assert {"university.create", "invites.create", "schedule.import", "campus.graph.replace"} <= {
        a["action"] for a in audit
    }


async def test_model_registry_activation_and_wakeword_download(client, tenant, providers, tmp_path):
    from doomich_api.config import get_settings

    registry = ModelRegistry(get_settings().registry_dir)
    artifacts = tmp_path / "ww"
    artifacts.mkdir()
    (artifacts / "model.onnx").write_bytes(b"onnx-bytes")
    manifest = Manifest(
        kind=ModelKind.WAKEWORD, tenant="_global", version="v1", artifacts={"onnx": "model.onnx"}, metrics={"frr": 0.03}
    )
    registry.register(manifest, artifacts)

    user = await register(client, tenant)
    assert (await client.get("/v1/models/wakeword", headers=user["headers"])).status_code == 404

    headers = await _admin_headers(client)
    resp = await client.post(
        "/admin/v1/models/activate",
        json={"tenant": "_global", "kind": "wakeword", "scope": "default", "version": "v1"},
        headers=headers,
    )
    assert resp.status_code == 200
    info = (await client.get("/v1/models/wakeword", headers=user["headers"])).json()
    assert info["version"] == "v1" and info["metrics"]["frr"] == 0.03
    blob = await client.get("/v1/models/wakeword/file", headers=user["headers"])
    assert blob.content == b"onnx-bytes"


async def test_non_admin_cannot_use_admin_api(client, tenant):
    user = await register(client, tenant)
    resp = await client.get("/admin/v1/universities", headers=user["headers"])
    assert resp.status_code == 401
