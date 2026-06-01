import html
import json
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from .. import auth as authmod, db
from .threads import _assert_thread_access

router = APIRouter(prefix="/api/translate", tags=["translate"])

_schema_ready = False


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS message_translations (
          message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
          target TEXT NOT NULL,
          pairs JSONB NOT NULL,
          provider TEXT,
          model TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY(message_id, target)
        );
        """
    )
    _schema_ready = True


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw or "")
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"[ \t\r\f\v]+", " ", raw).strip()


DECORATION_RE = re.compile(r"^[\s━─\-_=—―~*・･]+$")


def _paragraphs(text: str, limit: int = 60) -> list[str]:
    parts = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n{2,}|\n", text or "")]
    parts = [p for p in parts if len(p) >= 3 and not DECORATION_RE.fullmatch(p)]
    merged: list[str] = []
    for part in parts:
        if len(part) > 900:
            part = part[:900]
        merged.append(part)
        if len(merged) >= limit:
            break
    if not merged and text:
        merged.append(text[:900])
    return merged


def _cache_matches_body(pairs: Any, paragraphs: list[str]) -> bool:
    if not isinstance(pairs, list) or len(pairs) != len(paragraphs):
        return False
    for pair, paragraph in zip(pairs, paragraphs):
        if not isinstance(pair, dict):
            return False
        if str(pair.get("src") or "").strip() != paragraph:
            return False
    return True


def _extract_json(raw: str) -> dict[str, Any]:
    s = raw.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        s = "\n".join(lines[1:-1]) if len(lines) >= 3 else s
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        l, r = s.find("{"), s.rfind("}")
        if l >= 0 and r > l:
            return json.loads(s[l : r + 1])
        raise


def _ai_config() -> dict:
    cfg = db.fetchone(
        "SELECT provider, endpoint, api_key, model, enabled FROM ai_config WHERE id=1"
    )
    if not cfg or not cfg.get("enabled") or not cfg.get("api_key"):
        raise HTTPException(503, "AI 翻译未配置")
    return cfg


def _call_openai(cfg: dict, paragraphs: list[str], target: str) -> dict:
    url = cfg["endpoint"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    system = (
        "你是邮件翻译助手。把邮件段落翻译成目标语言，保留数字、金额、订单号、链接文字。"
        "必须逐段翻译每个输入段落，src 原样复制输入段落。"
        "严格返回 JSON: {\"pairs\":[{\"src\":\"原文段落\",\"tgt\":\"译文\"}]}。"
    )
    user_prompt = json.dumps({"target": target, "paragraphs": paragraphs}, ensure_ascii=False)
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    r = httpx.post(url, headers=headers, json=body, timeout=60)
    r.raise_for_status()
    return _extract_json(r.json()["choices"][0]["message"]["content"])


def _call_anthropic(cfg: dict, paragraphs: list[str], target: str) -> dict:
    url = cfg["endpoint"].rstrip("/") + "/v1/messages"
    headers = {
        "x-api-key": cfg["api_key"],
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    system = "你是邮件翻译助手。严格返回纯 JSON，不要 markdown。"
    user_prompt = (
        "把这些邮件段落翻译成目标语言，保留数字、金额、订单号、链接文字。"
        "必须逐段翻译每个输入段落，src 原样复制输入段落。"
        "返回 {\"pairs\":[{\"src\":\"原文段落\",\"tgt\":\"译文\"}]}。\n"
        + json.dumps({"target": target, "paragraphs": paragraphs}, ensure_ascii=False)
    )
    r = httpx.post(
        url,
        headers=headers,
        json={
            "model": cfg["model"],
            "max_tokens": 4000,
            "system": system,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": 0.1,
        },
        timeout=60,
    )
    r.raise_for_status()
    return _extract_json(r.json()["content"][0]["text"])


def _normalize_pairs(raw: Any, paragraphs: list[str]) -> list[dict[str, str]]:
    pairs = raw.get("pairs") if isinstance(raw, dict) else None
    if not isinstance(pairs, list):
        return []
    out = []
    for i, item in enumerate(pairs):
        if not isinstance(item, dict):
            continue
        src = str(paragraphs[i] if i < len(paragraphs) else item.get("src") or "").strip()
        tgt = str(item.get("tgt") or item.get("target") or item.get("translation") or "").strip()
        if src or tgt:
            out.append({"src": src, "tgt": tgt})
    return out


@router.post("/message/{message_id}")
def translate_message(
    message_id: int,
    target: str = Query("zh"),
    user: dict = Depends(authmod.get_current_user),
):
    ensure_schema()
    target = target.strip().lower() or "zh"
    msg = db.fetchone(
        """
        SELECT m.id, m.thread_id, m.body_text, m.body_html, m.snippet
        FROM messages m
        WHERE m.id=%s
        """,
        (message_id,),
    )
    if not msg:
        raise HTTPException(404, "邮件不存在")
    _assert_thread_access(msg["thread_id"], user)

    text = (msg.get("body_text") or "").strip()
    if not text:
        text = _html_to_text(msg.get("body_html") or "")
    if not text:
        text = msg.get("snippet") or ""
    paragraphs = _paragraphs(text)
    if not paragraphs:
        return {"pairs": []}

    cached = db.fetchone(
        "SELECT pairs FROM message_translations WHERE message_id=%s AND target=%s",
        (message_id, target),
    )
    if cached and _cache_matches_body(cached["pairs"], paragraphs):
        return {"pairs": cached["pairs"], "cached": True}

    cfg = _ai_config()
    try:
        raw = (
            _call_anthropic(cfg, paragraphs, target)
            if cfg.get("provider") == "anthropic"
            else _call_openai(cfg, paragraphs, target)
        )
        pairs = _normalize_pairs(raw, paragraphs)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"AI 翻译失败: {e}") from e
    except Exception as e:
        raise HTTPException(502, f"AI 翻译结果解析失败: {e}") from e

    if not pairs:
        raise HTTPException(502, "AI 翻译返回为空")

    db.execute(
        """
        INSERT INTO message_translations (message_id, target, pairs, provider, model, updated_at)
        VALUES (%s, %s, %s::jsonb, %s, %s, now())
        ON CONFLICT (message_id, target) DO UPDATE SET
          pairs=EXCLUDED.pairs,
          provider=EXCLUDED.provider,
          model=EXCLUDED.model,
          updated_at=now()
        """,
        (message_id, target, json.dumps(pairs, ensure_ascii=False), cfg.get("provider"), cfg.get("model")),
    )
    return {"pairs": pairs, "cached": False}
