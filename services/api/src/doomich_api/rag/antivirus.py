"""Проверка файлов антивирусом ClamAV (clamd, протокол INSTREAM). Включается DOOMICH_CLAMAV_HOST."""

from __future__ import annotations

import asyncio
import struct

from doomich_api.config import get_settings


class VirusFound(ValueError):
    pass


async def scan(data: bytes) -> None:
    settings = get_settings()
    if not settings.clamav_host:
        return
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(settings.clamav_host, settings.clamav_port), timeout=10
    )
    try:
        writer.write(b"zINSTREAM\0")
        for i in range(0, len(data), 64 * 1024):
            part = data[i : i + 64 * 1024]
            writer.write(struct.pack("!L", len(part)) + part)
        writer.write(struct.pack("!L", 0))
        await writer.drain()
        reply = (await asyncio.wait_for(reader.read(4096), timeout=60)).decode(errors="ignore")
    finally:
        writer.close()
    if "FOUND" in reply:
        raise VirusFound("Файл не прошёл антивирусную проверку")
