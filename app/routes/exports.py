import os
from email.message import EmailMessage
from email.utils import formatdate

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse

from .. import auth as authmod, db
from .threads import _assert_thread_access

router = APIRouter(prefix="/api/exports", tags=["exports"])


def _message_to_eml(row: dict) -> bytes:
    msg = EmailMessage()
    msg["From"] = row.get("from_email") or "unknown"
    if row.get("to_emails"):
        msg["To"] = ", ".join(row["to_emails"])
    if row.get("cc_emails"):
        msg["Cc"] = ", ".join(row["cc_emails"])
    if row.get("subject"):
        msg["Subject"] = row["subject"]
    if row.get("message_id"):
        msg["Message-ID"] = f"<{row['message_id']}>"
    msg["Date"] = formatdate(localtime=True)
    if row.get("body_html"):
        msg.set_content(row.get("body_text") or "")
        msg.add_alternative(row["body_html"], subtype="html")
    else:
        msg.set_content(row.get("body_text") or row.get("snippet") or "")
    return bytes(msg)


def _thread_messages(thread_id: int) -> list[dict]:
    return db.fetchall(
        """SELECT id, message_id, subject, from_email::text AS from_email,
                  to_emails::text[] AS to_emails, cc_emails::text[] AS cc_emails,
                  body_text, body_html, snippet, raw_path, received_at
           FROM messages
           WHERE thread_id=%s
           ORDER BY received_at ASC, id ASC""",
        (thread_id,),
    )


@router.get("/thread/{thread_id}.eml")
def export_thread_latest_eml(thread_id: int, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    rows = _thread_messages(thread_id)
    if not rows:
        raise HTTPException(404, "邮件不存在")
    row = rows[-1]
    if row.get("raw_path") and os.path.exists(row["raw_path"]):
        return FileResponse(
            row["raw_path"],
            filename=f"thread-{thread_id}-latest.eml",
            media_type="message/rfc822",
        )
    return Response(
        _message_to_eml(row),
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="thread-{thread_id}-latest.eml"'},
    )


@router.get("/thread/{thread_id}.mbox")
def export_thread_mbox(thread_id: int, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    rows = _thread_messages(thread_id)
    if not rows:
        raise HTTPException(404, "邮件不存在")
    parts: list[bytes] = []
    for row in rows:
        parts.append(b"From MAILHUB " + str(row.get("received_at") or "").encode("utf-8") + b"\n")
        if row.get("raw_path") and os.path.exists(row["raw_path"]):
            with open(row["raw_path"], "rb") as f:
                parts.append(f.read())
        else:
            parts.append(_message_to_eml(row))
        parts.append(b"\n\n")
    return Response(
        b"".join(parts),
        media_type="application/mbox",
        headers={"Content-Disposition": f'attachment; filename="thread-{thread_id}.mbox"'},
    )
