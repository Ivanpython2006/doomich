from __future__ import annotations

from sqlalchemy import select

from tests.conftest import register


async def test_pseudonyms_and_login_check(client, tenant):
    resp = await client.get("/v1/auth/pseudonyms", params={"locale": "ru"})
    assert len(resp.json()["suggestions"]) == 5
    resp = await client.post("/v1/auth/check-login", json={"login": "Иван Петров"})
    body = resp.json()
    assert body["looks_like_name"] is True
    assert body["valid"] is False  # пробел недопустим


async def test_invite_check_and_register(client, tenant):
    code = (await tenant.invites())[0]
    resp = await client.post("/v1/auth/invite/check", json={"code": code.lower().replace("-", " ")})
    assert resp.json() == {"valid": True, "university": "Тестовый университет", "role": "student", "group": "ИВТ-21-1"}

    resp = await client.post(
        "/v1/auth/register",
        json={"invite_code": code, "login": "ТихийЕнот42", "password": "очень-надёжный-пароль-1"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["recovery_code"] and len(data["recovery_code"].replace("-", "")) == 20
    assert data["user"]["group"]["code"] == "ИВТ-21-1"
    assert data["user"]["role"] == "student"

    # одноразовый код больше не работает
    resp = await client.post(
        "/v1/auth/register", json={"invite_code": code, "login": "ДругойЕнот", "password": "очень-надёжный-пароль-1"}
    )
    assert resp.status_code == 400


async def test_no_personal_data_is_stored(client, tenant):
    data = await register(client, tenant, login="ЯсныйФилин7")
    from doomich_api.db import RlsContext, session_scope
    from doomich_api.models import AppUser

    async with session_scope(RlsContext.system()) as session:
        user = (await session.execute(select(AppUser).where(AppUser.login == "ЯсныйФилин7"))).scalar_one()
        columns = {c.name for c in AppUser.__table__.columns}
    assert not columns & {"email", "phone", "name", "birthday", "ip"}
    assert user.password_hash.startswith("$argon2id$")
    assert data["recovery_code"] not in user.recovery_hash


async def test_duplicate_login_rejected(client, tenant):
    await register(client, tenant, login="СмелыйЛис1")
    code = (await tenant.invites())[0]
    resp = await client.post(
        "/v1/auth/register", json={"invite_code": code, "login": "смелыйлис1", "password": "очень-надёжный-пароль-1"}
    )
    assert resp.status_code == 409


async def test_login_refresh_rotation_and_reuse_detection(client, tenant):
    data = await register(client, tenant, login="МудрыйКит3")
    resp = await client.post("/v1/auth/login", json={"login": "мудрыйкит3", "password": "неверный-пароль-123"})
    assert resp.status_code == 401
    resp = await client.post("/v1/auth/login", json={"login": "мудрыйкит3", "password": "очень-надёжный-пароль-1"})
    assert resp.status_code == 200

    first = data["refresh_token"]
    rotated = await client.post("/v1/auth/refresh", json={"refresh_token": first})
    assert rotated.status_code == 200
    second = rotated.json()["refresh_token"]
    assert second != first
    # повторное использование старого токена отзывает всю цепочку
    reuse = await client.post("/v1/auth/refresh", json={"refresh_token": first})
    assert reuse.status_code == 401
    after = await client.post("/v1/auth/refresh", json={"refresh_token": second})
    assert after.status_code == 401


async def test_recover_with_code(client, tenant):
    data = await register(client, tenant, login="ЛовкийЁж5")
    resp = await client.post(
        "/v1/auth/recover",
        json={
            "login": "ЛовкийЁж5",
            "recovery_code": "WRONG-CODE-0000-0000-0000",
            "new_password": "новый-пароль-очень-1",
        },
    )
    assert resp.status_code == 401
    resp = await client.post(
        "/v1/auth/recover",
        json={
            "login": "ЛовкийЁж5",
            "recovery_code": data["recovery_code"].lower(),
            "new_password": "новый-пароль-очень-1",
        },
    )
    assert resp.status_code == 200, resp.text
    new_code = resp.json()["recovery_code"]
    assert new_code != data["recovery_code"]
    ok = await client.post("/v1/auth/login", json={"login": "ЛовкийЁж5", "password": "новый-пароль-очень-1"})
    assert ok.status_code == 200


async def test_me_patch_and_delete_account(client, tenant):
    data = await register(client, tenant)
    resp = await client.patch(
        "/v1/me", json={"locale": "en", "history_days": 7, "clear_group": True}, headers=data["headers"]
    )
    assert resp.status_code == 200
    me = resp.json()
    assert me["locale"] == "en" and me["history_days"] == 7 and me["group"] is None

    groups = await client.get("/v1/groups", params={"q": "ивт"}, headers=data["headers"])
    assert groups.json()[0]["code"] == "ИВТ-21-1"

    bad = await client.request("DELETE", "/v1/account", json={"password": "не-тот-пароль-123"}, headers=data["headers"])
    assert bad.status_code == 401
    resp = await client.request(
        "DELETE", "/v1/account", json={"password": "очень-надёжный-пароль-1"}, headers=data["headers"]
    )
    assert resp.status_code == 200
    gone = await client.get("/v1/me", headers=data["headers"])
    assert gone.status_code == 401


async def test_qr_login_flow(client, tenant):
    phone = await register(client, tenant)
    start = (await client.post("/v1/auth/qr/start")).json()
    pending = await client.post(
        "/v1/auth/qr/poll", json={"challenge_id": start["challenge_id"], "secret": start["secret"]}
    )
    assert pending.json() is None
    ok = await client.post("/v1/auth/qr/approve", json={"secret": start["secret"]}, headers=phone["headers"])
    assert ok.status_code == 200
    tokens = await client.post(
        "/v1/auth/qr/poll", json={"challenge_id": start["challenge_id"], "secret": start["secret"]}
    )
    assert tokens.json()["user"]["id"] == phone["user"]["id"]
