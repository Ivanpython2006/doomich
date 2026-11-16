from __future__ import annotations

from doomich_tts.textnorm import normalize, number_ru, year_genitive_ru
from fastapi.testclient import TestClient


def test_numbers_ru():
    assert number_ru(0) == "ноль"
    assert number_ru(21) == "двадцать один"
    assert number_ru(2) == "два" and number_ru(2, feminine=True) == "две"
    assert number_ru(2026) == "две тысячи двадцать шесть"
    assert number_ru(1_001_000) == "один миллион одна тысяча"
    assert number_ru(512) == "пятьсот двенадцать"


def test_year_genitive():
    assert year_genitive_ru(2026) == "две тысячи двадцать шестого"
    assert year_genitive_ru(2020) == "две тысячи двадцатого"
    assert year_genitive_ru(2000) == "двухтысячного"
    assert year_genitive_ru(1999) == "одна тысяча девятьсот девяносто девятого"
    assert year_genitive_ru(2011) == "две тысячи одиннадцатого"


def test_normalize_ru():
    text = "Пара в 09:30, ауд. 305, 16.11.2026; явка 25%, т.е. почти все."
    assert normalize(text) == (
        "Пара в девять тридцать, аудитория триста пять, шестнадцатое ноября две тысячи двадцать шестого года; "
        "явка двадцать пять процентов, то есть почти все."
    )
    assert normalize("Длина 2,5 м") == "Длина два запятая пять м"


def test_normalize_en():
    assert (
        normalize("Room 305 at 10:00, 21 students", "en")
        == "Room three hundred five at ten o'clock, twenty-one students"
    )


def test_speak_wav(monkeypatch):
    from doomich_tts import main

    main.get_settings.cache_clear()
    client = TestClient(main.create_app())
    resp = client.post("/v1/speak", json={"text": "Привет, у тебя 2 пары", "language": "ru"})
    assert resp.status_code == 200
    assert resp.content[:4] == b"RIFF" and resp.headers["x-sample-rate"] == "22050"
    voices = client.get("/v1/voices").json()
    assert {v["language"] for v in voices} == {"ru", "en"}
    assert (
        client.post("/v1/normalize", json={"text": "в 8:05", "language": "ru"}).json()["text"] == "в восемь ноль пять"
    )
