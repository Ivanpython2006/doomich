"""Публичная страница приглашения.

QR на листе приглашений содержит ссылку `<public_base_url>/invite/<код>`. Приложение «Думыч» само достаёт
код из такой ссылки, а если QR отсканировать обычной камерой телефона, откроется эта страница:
код крупно и что делать дальше. Страница не обращается к БД и не сообщает, существует ли код.
"""

from __future__ import annotations

import html

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from doomich_api.config import get_settings
from doomich_api.security import CODE_ALPHABET, format_groups, normalize_code

router = APIRouter(include_in_schema=False)

_PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Приглашение в «Думыч»</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 0; background: #f6f5fb; color: #1b1b21; }}
  main {{ max-width: 28rem; margin: 0 auto; padding: 2.5rem 1.25rem; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 .5rem; }}
  .code {{ font: 700 2.2rem/1.2 ui-monospace, monospace; letter-spacing: .12em; background: #fff;
          border-radius: 1rem; padding: 1.25rem; text-align: center; margin: 1.5rem 0; user-select: all; }}
  ol {{ padding-left: 1.25rem; line-height: 1.6; }}
  a.button {{ display: inline-block; background: #4f5b93; color: #fff; padding: .75rem 1.25rem;
             border-radius: 2rem; text-decoration: none; margin-top: 1rem; }}
  .muted {{ color: #5d5e67; font-size: .9rem; margin-top: 2rem; }}
</style>
</head>
<body>
<main>
  <h1>Вас пригласили в «Думыч»</h1>
  <p>Думыч — ИИ-помощник студента: расписание, ответы по учебным материалам и голосовой режим.</p>
  {body}
  <p class="muted">Регистрация без телефона, почты и имени — только псевдоним и пароль.</p>
</main>
</body>
</html>
"""


@router.get("/invite/{code}", response_class=HTMLResponse)
async def invite_page(code: str) -> HTMLResponse:
    normalized = normalize_code(code)
    downloads = get_settings().downloads_url
    install = (
        f'<a class="button" href="{html.escape(downloads, quote=True)}">Скачать приложение</a>' if downloads else ""
    )
    if len(normalized) == 8 and all(c in CODE_ALPHABET for c in normalized):
        body = f"""<p>Ваш код приглашения:</p>
  <div class="code">{format_groups(normalized)}</div>
  <ol>
    <li>Установите приложение «Думыч» на телефон или компьютер.</li>
    <li>Нажмите «Начать» и введите этот код или отсканируйте QR с листа приглашения.</li>
    <li>Придумайте псевдоним и пароль — и всё готово.</li>
  </ol>
  {install}"""
    else:
        body = f"<p>Ссылка повреждена: проверьте код на листе приглашения и введите его в приложении.</p>{install}"
    return HTMLResponse(_PAGE.format(body=body), headers={"Cache-Control": "no-store"})
