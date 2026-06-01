"""Telegram bot push helper."""
import httpx
from . import db


async def push(text: str, parse_mode: str = "HTML") -> bool:
    cfg = db.fetchone("SELECT bot_token, chat_id, enabled FROM tg_config WHERE id=1")
    if not cfg or not cfg["enabled"] or not cfg["bot_token"] or not cfg["chat_id"]:
        return False
    url = f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            url,
            json={
                "chat_id": cfg["chat_id"],
                "text": text[:4000],
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
        )
        return r.status_code == 200


def push_sync(text: str, parse_mode: str = "HTML") -> bool:
    cfg = db.fetchone("SELECT bot_token, chat_id, enabled FROM tg_config WHERE id=1")
    if not cfg or not cfg["enabled"] or not cfg["bot_token"] or not cfg["chat_id"]:
        return False
    url = f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage"
    r = httpx.post(
        url,
        json={
            "chat_id": cfg["chat_id"],
            "text": text[:4000],
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        },
        timeout=15,
    )
    return r.status_code == 200
