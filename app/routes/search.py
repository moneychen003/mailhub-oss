import re
from html import escape
from typing import Any

from fastapi import APIRouter, Depends, Query

from .. import auth as authmod, db
from .business import _event_type, _extract_business_fields, _extract_keys, _html_to_text, _merge_key, _search_text

router = APIRouter(prefix="/api/search", tags=["search"])


def _visibility_clause(user: dict) -> tuple[str, list[Any]]:
    if user.get("role") == "admin":
        return "", []
    user_email = (user.get("email") or "").lower()
    if not user_email:
        return " AND false", []
    return " AND EXISTS (SELECT 1 FROM unnest(t.participants) p WHERE lower(p)=%s)", [user_email]


def _highlight(value: str | None, q: str) -> str:
    text = value or ""
    if not q:
        return escape(text)
    pattern = re.compile(re.escape(q), re.I)
    out = []
    last = 0
    for m in pattern.finditer(text):
        out.append(escape(text[last:m.start()]))
        out.append(f"<mark>{escape(m.group(0))}</mark>")
        last = m.end()
    out.append(escape(text[last:]))
    return "".join(out)


ZH_VARIANTS = (
    ("提货", "提貨"),
    ("取货", "取貨"),
    ("送货", "送貨"),
    ("运单", "運單"),
    ("货件", "貨件"),
    ("收费", "收費"),
    ("仓储", "倉儲"),
    ("仓库", "倉庫"),
    ("逾期费用", "逾期費用"),
    ("密码", "密碼"),
    ("手机号码", "手機號碼"),
    ("手机号", "手機號碼"),
    ("实际", "實際"),
    ("实重", "實重"),
)


def _query_variants(query: str) -> list[str]:
    variants = {query}
    for simp, trad in ZH_VARIANTS:
        for value in list(variants):
            variants.add(value.replace(simp, trad))
            variants.add(value.replace(trad, simp))
    return [v for v in variants if v]


def _allow_body_search(variants: list[str]) -> bool:
    # Body/HTML search is valuable for structured facts (pickup codes, weights,
    # Chinese field names), but broad Latin vendor words in HTML footers produce
    # thousands of noisy matches and make the UI feel empty while waiting.
    for value in variants:
        compact = re.sub(r"\s+", "", value)
        if compact.isdigit() and len(compact) < 4:
            continue
        if re.search(r"[\u3400-\u9fff]", value):
            return True
        if re.search(r"\d", value) and len(compact) >= 4:
            return True
    return False


def _excerpt(value: str | None, variants: list[str], radius: int = 110) -> tuple[str, str]:
    text = value or ""
    if not text:
        return "", variants[0]
    lower = text.lower()
    for variant in variants:
        idx = lower.find(variant.lower())
        if idx >= 0:
            start = max(0, idx - radius)
            end = min(len(text), idx + len(variant) + radius)
            prefix = "..." if start else ""
            suffix = "..." if end < len(text) else ""
            return prefix + text[start:end] + suffix, variant
    return text[: radius * 2], variants[0]


def _business_groups(rows: list[dict], user: dict) -> list[dict]:
    del user
    groups: dict[str, dict] = {}
    for row in rows:
        for key in _extract_keys(_search_text(row)):
            merge_id = _merge_key(key)
            group = groups.setdefault(
                merge_id,
                {
                    **key,
                    "tracking_number": key.get("tracking_number"),
                    "events": [],
                },
            )
            group["tracking_number"] = group.get("tracking_number") or key.get("tracking_number")
            if key.get("order_id"):
                group.setdefault("order_id", key["order_id"])
            if key.get("shipment_id"):
                group.setdefault("shipment_id", key["shipment_id"])
            group["events"].append(
                {
                    "id": row["message_id"],
                    "thread_id": row["thread_id"],
                    "event_type": _event_type(row),
                    "occurred_at": row["received_at"],
                    "msg_subject": row.get("subject") or row.get("subject_initial"),
                }
            )

    out = []
    for key in groups.values():
        events = sorted(key["events"], key=lambda e: (e.get("occurred_at") or "", e.get("id") or 0))
        if not events:
            continue
        latest = events[-1]
        out.append(
            {
                "vendor": key.get("vendor") or "GENERAL",
                "order_id": key.get("order_id"),
                "tracking_number": key.get("tracking_number"),
                "shipment_key": _merge_key(key),
                "latest_thread_id": latest["thread_id"],
                "latest_subject": latest.get("msg_subject"),
                "latest_event": latest["event_type"],
                "last_at": latest["occurred_at"],
                "event_count": len(events),
                "thread_count": len({e["thread_id"] for e in events}),
                "event_types": [e["event_type"] for e in events],
            }
        )
    return sorted(out, key=lambda x: x.get("last_at") or "", reverse=True)[:20]


@router.get("")
def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=100),
    user: dict = Depends(authmod.get_current_user),
):
    query = q.strip()
    if not query:
        return {"items": [], "total": 0, "business_groups": []}

    variants = _query_variants(query)
    likes = [f"%{v}%" for v in variants]
    branches: list[str] = [
        "SELECT id FROM messages WHERE from_email::text ILIKE ANY(%s)",
        "SELECT id FROM messages WHERE from_name ILIKE ANY(%s)",
        "SELECT id FROM messages WHERE subject ILIKE ANY(%s)",
        "SELECT id FROM messages WHERE snippet ILIKE ANY(%s)",
        "SELECT m.id FROM messages m JOIN threads ts ON ts.id = m.thread_id WHERE ts.subject_initial ILIKE ANY(%s)",
    ]
    branch_params: list[Any] = [likes, likes, likes, likes, likes]
    if _allow_body_search(variants):
        branches.extend(
            [
                "SELECT id FROM messages WHERE body_text ILIKE ANY(%s)",
                "SELECT id FROM messages WHERE body_html ILIKE ANY(%s)",
            ]
        )
        branch_params.extend([likes, likes])
    visible, extra = _visibility_clause(user)
    rows = db.fetchall(
        f"""
        WITH matched_messages AS (
          {" UNION ".join(branches)}
        )
        SELECT m.id AS message_id, m.thread_id, m.subject, m.from_email::text AS from_email,
               m.from_name, m.snippet, m.body_text, m.body_html, m.received_at,
               t.subject_initial, t.ai_priority, t.ai_category,
               count(*) OVER() AS total_count
        FROM messages m
        JOIN matched_messages mm ON mm.id = m.id
        JOIN threads t ON t.id = m.thread_id
        WHERE true
        {visible}
        ORDER BY m.received_at DESC NULLS LAST, m.id DESC
        LIMIT %s
        """,
        tuple(branch_params + extra + [limit]),
    )
    total = rows[0]["total_count"] if rows else 0
    items = []
    for row in rows:
        html_text = _html_to_text(row.get("body_html"))
        excerpt, matched = _excerpt(row.get("snippet"), variants)
        if not any(v.lower() in excerpt.lower() for v in variants):
            excerpt, matched = _excerpt(row.get("body_text"), variants)
        if not any(v.lower() in excerpt.lower() for v in variants):
            excerpt, matched = _excerpt(html_text, variants)
        item = {k: v for k, v in row.items() if k != "body_html"}
        item["snippet_hl"] = _highlight(excerpt, matched)
        item["business_fields"] = _extract_business_fields(row)
        items.append(item)
    return {"items": items, "total": total, "business_groups": _business_groups(rows, user)}
