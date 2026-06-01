import re
from collections import OrderedDict
from html import unescape
from typing import Any

from fastapi import APIRouter, Depends, Query

from .. import auth as authmod, db
from .threads import _assert_thread_access

router = APIRouter(prefix="/api/business", tags=["business"])

APPLE_ORDER_RE = re.compile(r"\bW\d{9,12}\b", re.I)
UPS_RE = re.compile(r"\b1Z[A-Z0-9]{10,22}\b", re.I)
BUYANDSHIP_RE = re.compile(
    r"(?:轉運單編號|转运单编号|運單編號|运单编号|貨件編號|货件编号|貨件|货件|shipment|package)\s*[:#：]?\s*([0-9]{6,12})",
    re.I,
)
SHOPIFY_RE = re.compile(r"\border\s*#\s*([0-9]{3,12})\b", re.I)
TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.I | re.S)


def _html_to_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|td|th)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _clean_cell(value: str | None) -> str:
    text = _html_to_text(value)
    return re.sub(r"\s+", " ", text).strip()


def _text(row: dict) -> str:
    return " ".join(
        str(row.get(k) or "")
        for k in ("from_email", "from_name", "subject", "subject_initial", "snippet", "body_text")
    )


def _search_text(row: dict) -> str:
    return " ".join([_text(row), _html_to_text(row.get("body_html"))])


def _event_signal_text(row: dict) -> str:
    # Event classification must not scan body_html: Apple footers contain
    # "Sales and Refunds", and CSS comments can mention "canceled items".
    text = _text(row)
    return re.sub(r"\s+", " ", text).strip().lower()


def _vendor(raw: str) -> str:
    s = raw.lower()
    if "buyandship" in s or "buy&ship" in s:
        return "BUYANDSHIP"
    if "orders.apple.com" in s or "email.apple.com" in s or "apple" in s:
        return "APPLE"
    if "shopifyemail" in s or "shopify" in s:
        return "SHOPIFY"
    return "GENERAL"


def _extract_keys(raw: str) -> list[dict[str, str]]:
    vendor = _vendor(raw)
    keys: list[dict[str, str]] = []

    shipment_ids = list(dict.fromkeys(m.group(1) for m in BUYANDSHIP_RE.finditer(raw)))
    tracking_numbers = list(dict.fromkeys(m.group(0).upper() for m in UPS_RE.finditer(raw)))
    apple_order_ids = list(dict.fromkeys(m.group(0).upper() for m in APPLE_ORDER_RE.finditer(raw)))

    for order_id in apple_order_ids:
        key = {"vendor": "APPLE", "order_id": order_id, "shipment_key": f"order:{order_id}"}
        if tracking_numbers:
            key["tracking_number"] = tracking_numbers[0]
        keys.append(key)

    for shipment_id in shipment_ids:
        key = {"vendor": "BUYANDSHIP", "shipment_id": shipment_id, "shipment_key": f"pkg:{shipment_id}"}
        if tracking_numbers:
            key["tracking_number"] = tracking_numbers[0]
        keys.append(key)

    if not shipment_ids and not (vendor == "APPLE" and apple_order_ids):
        for tracking in tracking_numbers:
            keys.append({"vendor": "BUYANDSHIP" if vendor == "BUYANDSHIP" else vendor, "tracking_number": tracking, "shipment_key": f"trk:{tracking}"})

    if vendor == "SHOPIFY":
        for order_id in dict.fromkeys(m.group(1) for m in SHOPIFY_RE.finditer(raw)):
            keys.append({"vendor": "SHOPIFY", "order_id": f"#{order_id}", "shipment_key": f"shopify:{order_id}"})

    return keys


def _buyandship_table_fields(html: str | None) -> dict[str, str]:
    fields: dict[str, str] = {}
    if not html:
        return fields
    for tr in TR_RE.findall(html):
        cells = CELL_RE.findall(tr)
        if len(cells) < 2:
            continue
        label = _clean_cell(cells[0])
        value = _clean_cell(cells[1])
        if not label or not value:
            continue
        if "提貨密碼" in label or "提货密码" in label:
            m = re.search(r"\b\d{4,8}\b", value)
            if m:
                fields["pickup_code"] = m.group(0)
        elif "運單編號" in label or "运单编号" in label:
            fields["waybill_number"] = value.split()[0]
        elif "貨件" in label or "货件" in label:
            m = re.search(r"\b([A-Z0-9]{10,30})\s*\(([^)]+)\)", value, re.I)
            if m:
                fields["package_id"] = m.group(1)
                fields["package_weight"] = m.group(2)
            else:
                fields["package_detail"] = value
        elif "取貨" in label or "取货" in label or "送貨地點" in label or "送货地点" in label:
            fields["pickup_location"] = value
        elif "總收費重量" in label or "总收费重量" in label:
            fields["chargeable_weight"] = value
        elif label in ("收費", "收费") or "收費" in label or "收费" in label:
            fields["fee"] = value
        elif "備註" in label or "备注" in label:
            fields["note"] = value
    return fields


def _extract_business_fields(row: dict) -> dict[str, str]:
    raw = _search_text(row)
    fields = _buyandship_table_fields(row.get("body_html"))
    if not fields.get("pickup_code"):
        m = re.search(r"(?:提貨密碼|提货密码)\s*[:：]?\s*(\d{4,8})", raw)
        if m:
            fields["pickup_code"] = m.group(1)
    if not fields.get("waybill_number"):
        m = re.search(r"(?:運單編號|运单编号)\s*[:：]?\s*([A-Z0-9]{6,30})", raw, re.I)
        if m:
            fields["waybill_number"] = m.group(1)
    if not fields.get("chargeable_weight"):
        m = re.search(r"(?:總收費重量|总收费重量)\s*[:：]?\s*([0-9.]+\s*(?:磅|lb|kg|公斤))", raw, re.I)
        if m:
            fields["chargeable_weight"] = m.group(1)
    if not fields.get("package_weight"):
        m = re.search(r"\b([A-Z0-9]{10,30})\s*\(([0-9.]+\s*(?:lb|磅|kg|公斤))\)", raw, re.I)
        if m:
            fields["package_id"] = fields.get("package_id") or m.group(1)
            fields["package_weight"] = m.group(2)
    return fields


def _event_type(row: dict) -> str:
    s = _event_signal_text(row)
    vendor = _vendor(s)

    if vendor == "APPLE":
        if re.search(r"\byour shipment is on its way\b|\byour items have shipped\b|\bitems have shipped\b", s):
            return "shipped"
        if re.search(r"\bupdated information about your order\b|\bthere'?s been a change to your order\b", s):
            return "order_updated"
        if re.search(r"\byour order has been cancell?ed\b|\border .* has been cancell?ed\b", s):
            return "cancelled"
        if re.search(r"\byour refund\b|\brefund (?:is|has been|was|from)\b|\brefunded\b", s):
            return "returned"

    if re.search(r"\bcancell?ed\b|已取消|取消订单", s):
        return "cancelled"
    if any(x in s for x in ("out for delivery", "派送", "領取貨件", "领取货件", "提貨", "提货")):
        return "out_for_delivery"
    if re.search(r"\byour refund\b|\brefund (?:is|has been|was|from)\b|\brefunded\b|\breturned to sender\b|\bwill be returned\b|退款|退货|退回", s):
        return "returned"
    if any(x in s for x in ("delivered", "已送达", "已送達", "已完成", "签收", "簽收")):
        return "delivered"
    if any(x in s for x in ("shipped", "shipment", "dispatched", "出库", "已發貨", "已发货", "打包待發", "打包待发")):
        return "shipped"
    if any(x in s for x in ("warehouse", "到達香港倉庫", "到达香港仓库", "已入庫", "已入库", "集運操作", "集运操作")):
        return "in_warehouse"
    if any(x in s for x in ("payment required", "pay now", "待付款", "付款", "交钱", "繳費", "缴费")):
        return "payment_pending"
    if any(x in s for x in ("paid", "payment received", "已付款", "支付成功")):
        return "payment_done"
    if any(x in s for x in ("change confirmation", "updated information", "status updated", "配送信息已更新", "订单更新", "訂單更新")):
        return "order_updated"
    if any(x in s for x in ("we're processing your order", "order confirmation", "下单", "下單", "订单已创建", "訂單已建立")):
        return "order_placed"
    return "other"


def _visibility_clause(user: dict) -> tuple[str, list[Any]]:
    if user.get("role") == "admin":
        return "", []
    user_email = (user.get("email") or "").lower()
    if not user_email:
        return " AND false", []
    return " AND EXISTS (SELECT 1 FROM unnest(t.participants) p WHERE lower(p)=%s)", [user_email]


def _search_related(key: dict[str, str], user: dict) -> list[dict]:
    terms = [key.get("order_id"), key.get("shipment_id"), key.get("tracking_number")]
    # For keys extracted only from a UPS tracking number, search by that tracking number.
    if not any(terms):
        return []
    needle = next(t for t in terms if t)
    like = f"%{needle}%"
    visible, extra = _visibility_clause(user)
    return db.fetchall(
        f"""
        SELECT m.id, m.thread_id, m.subject, m.from_email::text AS from_email,
               m.from_name, m.snippet, m.body_text, m.body_html, m.received_at,
               t.subject_initial
        FROM messages m
        JOIN threads t ON t.id = m.thread_id
        WHERE (
          m.subject ILIKE %s
          OR m.snippet ILIKE %s
          OR m.body_text ILIKE %s
        )
        {visible}
        ORDER BY m.received_at ASC, m.id ASC
        LIMIT 80
        """,
        tuple([like, like, like] + extra),
    )


def _merge_key(key: dict[str, str]) -> str:
    return key.get("order_id") or key.get("shipment_id") or key.get("tracking_number") or key.get("shipment_key") or "unknown"


@router.get("/timeline")
def timeline(thread_id: int = Query(...), user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    current = db.fetchall(
        """
        SELECT m.id, m.thread_id, m.subject, m.from_email::text AS from_email,
               m.from_name, m.snippet, m.body_text, m.body_html, m.received_at,
               t.subject_initial
        FROM messages m
        JOIN threads t ON t.id = m.thread_id
        WHERE m.thread_id=%s
        ORDER BY m.received_at ASC
        """,
        (thread_id,),
    )
    extracted: "OrderedDict[str, dict[str, str]]" = OrderedDict()
    for row in current:
        for key in _extract_keys(_search_text(row)):
            extracted.setdefault(key["shipment_key"], key)

    orders = []
    for key in extracted.values():
        related = _search_related(key, user)
        events = []
        seen = set()
        tracking_number = key.get("tracking_number")
        fields: dict[str, str] = {}
        for row in related:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            row_fields = _extract_business_fields(row)
            fields.update({k: v for k, v in row_fields.items() if v and not fields.get(k)})
            row_keys = _extract_keys(_search_text(row))
            for row_key in row_keys:
                tracking_number = tracking_number or row_key.get("tracking_number")
                if row_key.get("order_id"):
                    key.setdefault("order_id", row_key["order_id"])
                if row_key.get("shipment_id"):
                    key.setdefault("shipment_id", row_key["shipment_id"])
            if row_fields.get("waybill_number"):
                key.setdefault("shipment_id", row_fields["waybill_number"])
            events.append(
                {
                    "id": row["id"],
                    "thread_id": row["thread_id"],
                    "event_type": _event_type(row),
                    "occurred_at": row["received_at"],
                    "msg_subject": row.get("subject") or row.get("subject_initial"),
                    "tracking_number": tracking_number,
                    "fields": row_fields,
                    "details": {
                        "from_email": row.get("from_email"),
                        "snippet": row.get("snippet"),
                        "subject": row.get("subject"),
                    },
                }
            )

        if not events:
            continue
        latest = events[-1]
        orders.append(
            {
                "vendor": key.get("vendor") or "GENERAL",
                "order_id": key.get("order_id"),
                "tracking_number": tracking_number,
                "fields": fields,
                "shipment_key": _merge_key(key),
                "latest_thread_id": latest["thread_id"],
                "latest_subject": latest.get("msg_subject"),
                "latest_event": latest["event_type"],
                "last_at": latest["occurred_at"],
                "event_count": len(events),
                "thread_count": len({e["thread_id"] for e in events}),
                "event_types": [e["event_type"] for e in events],
                "events": events,
            }
        )

    return {"orders": orders}
