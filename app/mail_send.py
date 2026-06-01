import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from . import db, outbound

OUTBOUND_DIR = Path(os.environ.get("MAILHUB_OUTBOUND_DIR", "/opt/mailhub/raw/outbound"))
UPLOAD_DIR = Path(os.environ.get("MAILHUB_UPLOAD_DIR", "/opt/mailhub/uploads/outbound"))


def clean_filename(name: str | None) -> str:
    value = os.path.basename(name or "attachment")
    value = re.sub(r"[\r\n\t]+", " ", value).strip()
    return value[:180] or "attachment"


def raw_path_for(mid: str) -> Path:
    OUTBOUND_DIR.mkdir(parents=True, exist_ok=True)
    safe = mid.replace("/", "_").replace("@", "_at_")
    return OUTBOUND_DIR / f"{safe}.eml"


def upload_path_for(user_id: int, token: str, filename: str) -> Path:
    root = UPLOAD_DIR / str(user_id)
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{token}_{clean_filename(filename)}"


def _content_type(filename: str | None, fallback: str | None = None) -> str:
    return fallback or mimetypes.guess_type(filename or "")[0] or "application/octet-stream"


def _attachment_rows(attachment_ids: list[int] | None, user_id: int) -> list[dict]:
    ids = [int(x) for x in (attachment_ids or []) if x]
    if not ids:
        return []
    rows = db.fetchall(
        """
        SELECT id, filename, content_type, size_bytes, disk_path
        FROM uploaded_attachments
        WHERE user_id=%s AND id=ANY(%s) AND deleted_at IS NULL
        ORDER BY id
        """,
        (user_id, ids),
    )
    found = {int(r["id"]) for r in rows}
    missing = [x for x in ids if x not in found]
    if missing:
        raise HTTPException(400, f"附件不存在或无权限: {missing[0]}")
    return rows


def _attach_files(msg, rows: list[dict]) -> None:
    for row in rows:
        path = row.get("disk_path")
        if not path or not os.path.exists(path):
            raise HTTPException(400, f"附件文件丢失: {row.get('filename') or row.get('id')}")
        ctype = _content_type(row.get("filename"), row.get("content_type"))
        maintype, subtype = ctype.split("/", 1) if "/" in ctype else ("application", "octet-stream")
        with open(path, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype=maintype,
                subtype=subtype,
                filename=row.get("filename") or f"attachment_{row['id']}",
            )


def send_outbound_message(
    *,
    thread_id: int,
    user_id: int,
    sender_id: int,
    to: list[str],
    cc: list[str] | None,
    bcc: list[str] | None,
    subject: str,
    body_text: str,
    body_html: str | None,
    in_reply_to: str | None = None,
    references: list[str] | None = None,
    attachment_ids: list[int] | None = None,
    event_action: str = "reply_sent",
) -> dict[str, Any]:
    sender = db.fetchone("SELECT email, display_name, signature_text, signature_html FROM senders WHERE id=%s", (sender_id,))
    if not sender:
        raise HTTPException(400, "发件人不存在")

    cc = cc or []
    bcc = bcc or []
    attachments = _attachment_rows(attachment_ids, user_id)
    if sender.get("signature_text") and sender["signature_text"] not in (body_text or ""):
        body_text = f"{body_text or ''}\n\n{sender['signature_text']}".strip()
    if sender.get("signature_html") and sender["signature_html"] not in (body_html or ""):
        body_html = f"{body_html or body_text or ''}<br><br>{sender['signature_html']}"
    msg, mid = outbound.build_message(
        from_email=sender["email"],
        from_name=sender["display_name"],
        to=to,
        cc=cc,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        in_reply_to=in_reply_to,
        references=references or [],
        bcc=bcc,
    )
    _attach_files(msg, attachments)
    raw_path = raw_path_for(mid)
    raw_bytes = bytes(msg)
    with open(raw_path, "wb") as f:
        f.write(raw_bytes)

    try:
        outbound.submit(msg)
        sent_status, sent_error = "sent", None
    except Exception as e:
        sent_status, sent_error = "failed", repr(e)

    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            """INSERT INTO messages
               (thread_id, direction, message_id, in_reply_to, references_chain,
                subject, from_email, from_name, to_emails, cc_emails, bcc_emails,
                body_text, body_html, snippet, raw_path, size_bytes, has_attachments,
                headers, received_at, parsed_at, parse_status, sent_at, sent_status, sent_error)
               VALUES (%s,'out',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       '{}'::jsonb,now(),now(),'parsed',now(),%s,%s)
               RETURNING id""",
            (
                thread_id,
                mid,
                in_reply_to,
                references or [],
                subject,
                sender["email"],
                sender["display_name"],
                to,
                cc,
                bcc,
                body_text,
                body_html,
                body_text[:200] if body_text else "",
                str(raw_path),
                len(raw_bytes),
                bool(attachments),
                sent_status,
                sent_error,
            ),
        )
        inserted = cur.fetchone()
        for att in attachments:
            cur.execute(
                """INSERT INTO attachments
                   (message_id, filename, content_type, size_bytes, disk_path)
                   VALUES (%s,%s,%s,%s,%s)""",
                (inserted["id"], att["filename"], att["content_type"], att["size_bytes"], att["disk_path"]),
            )
        if attachments:
            cur.execute(
                "UPDATE uploaded_attachments SET used_at=now() WHERE user_id=%s AND id=ANY(%s)",
                (user_id, [int(a["id"]) for a in attachments]),
            )
        cur.execute(
            "INSERT INTO events (user_id, action, target_type, target_id, payload) "
            "VALUES (%s, %s, 'thread', %s, %s::jsonb)",
            (
                user_id,
                event_action,
                thread_id,
                json.dumps({"sender": sender["email"], "to": to, "msg_id": mid}, ensure_ascii=False),
            ),
        )
        c.commit()

    result = {"id": inserted["id"], "message_id": mid, "sent_status": sent_status}
    if sent_status == "failed":
        result["sent_error"] = sent_error
    return result
