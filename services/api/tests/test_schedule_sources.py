from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.test_admin import _admin_headers


@pytest.fixture
def schedule_site(tenant) -> Iterator[int]:
    """Локальный «сайт расписания»: JSON с занятиями и перенаправление на другой хост."""
    lessons = {
        "data": {
            "lessons": [
                {
                    "group": {"name": tenant.group_code},
                    "date": "2027-03-01",
                    "time_start": "09:00",
                    "time_end": "10:30",
                    "discipline": "Алгоритмы",
                    "auditorium": "210",
                }
            ]
        }
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{self.server.server_port}/lessons.json")
                self.end_headers()
                return
            body = json.dumps(lessons).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port
    server.shutdown()


async def test_source_ssrf_protection_and_json_sync(client, tenant, schedule_site, monkeypatch):
    from doomich_api.config import get_settings

    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    headers = await _admin_headers(client)
    base = f"/admin/v1/universities/{tenant.university_id}/schedule/sources"
    bad = await client.post(base, json={"name": "ftp", "kind": "json", "config": {"url": "ftp://x/y"}}, headers=headers)
    assert bad.status_code == 422
    no_group = await client.post(
        base, json={"name": "ics", "kind": "ics", "config": {"url": "https://x"}}, headers=headers
    )
    assert no_group.status_code == 422

    config = {
        "url": f"http://127.0.0.1:{schedule_site}/lessons.json",
        "items": "data.lessons",
        "fields": {
            "group": "group.name",
            "date": "date",
            "start": "time_start",
            "end": "time_end",
            "subject": "discipline",
            "room": "auditorium",
        },
    }
    source = (await client.post(base, json={"name": "Сайт", "kind": "json", "config": config}, headers=headers)).json()

    # внутренний адрес без явного разрешения — отказ, сервер не запрашивается
    blocked = (await client.post(f"/admin/v1/schedule/sources/{source['id']}/sync", headers=headers)).json()
    assert blocked["status"] == "error" and "внутренней сети" in blocked["error"]

    monkeypatch.setattr(get_settings(), "schedule_source_private_hosts", ["127.0.0.1"])
    synced = (await client.post(f"/admin/v1/schedule/sources/{source['id']}/sync", headers=headers)).json()
    assert synced["added"] == 1
    listed = (await client.get(base, headers=headers)).json()
    assert next(s for s in listed if s["id"] == source["id"])["last_status"] == "ok"

    # перенаправление на неразрешённый хост тоже блокируется
    redirect = {**config, "url": f"http://127.0.0.1:{schedule_site}/redirect"}
    other = (
        await client.post(base, json={"name": "Редирект", "kind": "json", "config": redirect}, headers=headers)
    ).json()
    result = (await client.post(f"/admin/v1/schedule/sources/{other['id']}/sync", headers=headers)).json()
    assert result["status"] == "error" and "localhost" in result["error"]
