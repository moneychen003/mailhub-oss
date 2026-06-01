import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, EmailStr
from .. import db, auth as authmod
from ..mail_send import send_outbound_message
from ..send_queue import cancel_scheduled_send, queue_send

router = APIRouter(prefix="/api/threads", tags=["threads"])
_REPLY_PREFIX_RE = re.compile(r"^\s*(re|回复|回覆|答复|答覆)\s*[:：]", re.I)

_thread_state_schema_ready = False


def ensure_thread_state_schema() -> None:
    global _thread_state_schema_ready
    if _thread_state_schema_ready:
        return
    existing = {
        row["column_name"]
        for row in db.fetchall(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='threads'
            """
        )
    }
    missing = {"source", "flagged", "pinned", "pinned_at", "snoozed_until"} - existing
    if missing:
        # New installs should get these from schema.sql. Production DB users may
        # not own threads, so do not run DDL on every request when columns exist.
        with db.conn() as c, c.cursor() as cur:
            if "source" in missing:
                cur.execute("ALTER TABLE threads ADD COLUMN source TEXT")
            if "flagged" in missing:
                cur.execute("ALTER TABLE threads ADD COLUMN flagged BOOLEAN NOT NULL DEFAULT false")
            if "pinned" in missing:
                cur.execute("ALTER TABLE threads ADD COLUMN pinned BOOLEAN NOT NULL DEFAULT false")
            if "pinned_at" in missing:
                cur.execute("ALTER TABLE threads ADD COLUMN pinned_at TIMESTAMPTZ")
            if "snoozed_until" in missing:
                cur.execute("ALTER TABLE threads ADD COLUMN snoozed_until TIMESTAMPTZ")
            c.commit()
    _thread_state_schema_ready = True


@router.get("")
def list_threads(
    user: dict = Depends(authmod.get_current_user),
    status: str = Query("inbox"),
    priority: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    folder_id: Optional[int] = Query(None),
    source: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    due: Optional[str] = Query(None),
    snoozed: str = Query("active"),
    flagged: Optional[bool] = Query(None),
    pinned: Optional[bool] = Query(None),
    hide_low_value: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
):
    ensure_thread_state_schema()
    where = []
    params: list = []
    if status != "any":
        where.append("t.status = %s")
        params.append(status)
    # Per-user ACL: non-admin only sees threads they are a participant on.
    if user.get("role") != "admin":
        user_email = (user.get("email") or "").lower()
        if not user_email:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        where.append("EXISTS (SELECT 1 FROM unnest(t.participants) p WHERE lower(p) = %s)")
        params.append(user_email)
    if priority:
        priorities = [p.strip() for p in priority.split(",") if p.strip()]
        if len(priorities) == 1:
            where.append("t.ai_priority = %s")
            params.append(priorities[0])
        elif priorities:
            where.append("t.ai_priority = ANY(%s)")
            params.append(priorities)
    if category:
        cats = [c.strip() for c in category.split(",") if c.strip()]
        if cats:
            where.append("t.ai_category = ANY(%s)")
            params.append(cats)
    if source:
        where.append("COALESCE(NULLIF(t.source,''),'unknown') = %s")
        params.append(source)
    if snoozed == "active":
        where.append("(t.snoozed_until IS NULL OR t.snoozed_until <= now())")
    elif snoozed == "only":
        where.append("t.snoozed_until > now()")
    elif snoozed != "all":
        raise HTTPException(400, "snoozed 参数无效")
    if flagged is not None:
        where.append("t.flagged = %s")
        params.append(flagged)
    if pinned is not None:
        where.append("t.pinned = %s")
        params.append(pinned)
    if hide_low_value:
        where.append(
            "COALESCE(t.ai_priority, 'normal') NOT IN ('spam','low') "
            "AND COALESCE(t.ai_category, '') <> 'marketing'"
        )
    if due == "today":
        where.append("t.due_at IS NOT NULL AND t.due_at <= now() + interval '24 hours'")
    if direction in ("in", "out"):
        where.append("EXISTS (SELECT 1 FROM messages md WHERE md.thread_id=t.id AND md.direction=%s)")
        params.append(direction)
    if folder_id is not None:
        from .folders import ensure_schema as ensure_folder_schema

        ensure_folder_schema()
        where.append(
            "EXISTS (SELECT 1 FROM thread_folders tf WHERE tf.thread_id=t.id AND tf.folder_id=%s AND tf.user_id=%s)"
        )
        params.extend([folder_id, user["id"]])
    if q:
        where.append("(t.subject_initial ILIKE %s OR EXISTS (SELECT 1 FROM messages m WHERE m.thread_id=t.id AND (m.from_email::text ILIKE %s OR m.snippet ILIKE %s)))")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    offset = (page - 1) * page_size
    where_clause = " AND ".join(where) if where else "true"
    rows = db.fetchall(
        f"""
        SELECT
          t.id, t.subject_initial, t.participants, t.message_count,
          t.first_message_at, t.last_message_at,
          t.ai_priority, t.ai_category, t.ai_summary, t.ai_action,
          t.status, t.tags, t.due_at,
          COALESCE(NULLIF(t.source,''),'unknown') AS source,
          t.flagged, t.pinned, t.pinned_at, t.snoozed_until,
          (SELECT m.snippet FROM messages m WHERE m.thread_id=t.id ORDER BY m.received_at DESC LIMIT 1) AS last_snippet,
          (SELECT m.from_email FROM messages m WHERE m.thread_id=t.id ORDER BY m.received_at DESC LIMIT 1) AS last_from,
          NOT EXISTS (SELECT 1 FROM thread_reads tr WHERE tr.thread_id=t.id AND tr.user_id=%s) AS unread
        FROM threads t
        WHERE {where_clause}
        ORDER BY t.pinned DESC, t.pinned_at DESC NULLS LAST, t.last_message_at DESC NULLS LAST
        LIMIT %s OFFSET %s
        """,
        tuple([user["id"]] + params + [page_size, offset]),
    )
    total = db.fetchone(
        f"SELECT count(*) AS c FROM threads t WHERE {where_clause}",
        tuple(params),
    )["c"]
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def _user_can_see_thread(user: dict, thread: dict) -> bool:
    """ACL: admin sees everything; other users only see threads where they are
    a participant (by email). threads.participants is TEXT[] of all addresses
    seen on the thread (from_email + to_emails + cc_emails)."""
    if user.get("role") == "admin":
        return True
    user_email = (user.get("email") or "").lower()
    if not user_email:
        return False
    parts = thread.get("participants") or []
    for p in parts:
        if p and p.lower() == user_email:
            return True
    return False


@router.get("/{thread_id}")
def thread_detail(thread_id: int, user: dict = Depends(authmod.get_current_user)):
    ensure_thread_state_schema()
    t = db.fetchone("SELECT * FROM threads WHERE id=%s", (thread_id,))
    if not t:
        raise HTTPException(404, "线程不存在")
    if not _user_can_see_thread(user, t):
        # Return 404 rather than 403 to avoid leaking existence.
        raise HTTPException(404, "线程不存在")
    msgs = db.fetchall(
        """SELECT id, direction, message_id, in_reply_to, subject,
                  from_email, from_name,
                  to_emails::text[] AS to_emails,
                  cc_emails::text[] AS cc_emails,
                  reply_to,
                  body_text, body_html, snippet, size_bytes, has_attachments,
                  received_at, sent_at, sent_status
           FROM messages WHERE thread_id=%s ORDER BY received_at ASC""",
        (thread_id,),
    )
    atts = db.fetchall(
        """SELECT a.id, a.message_id, a.filename, a.content_type, a.size_bytes
           FROM attachments a JOIN messages m ON m.id=a.message_id
           WHERE m.thread_id=%s ORDER BY a.id""",
        (thread_id,),
    )
    # mark as read
    db.execute(
        "INSERT INTO thread_reads (thread_id, user_id) VALUES (%s, %s) "
        "ON CONFLICT (thread_id, user_id) DO UPDATE SET read_at = now()",
        (thread_id, user["id"]),
    )
    return {"thread": t, "messages": msgs, "attachments": atts}


def _assert_thread_access(thread_id: int, user: dict) -> dict:
    ensure_thread_state_schema()
    t = db.fetchone("SELECT * FROM threads WHERE id=%s", (thread_id,))
    if not t:
        raise HTTPException(404, "线程不存在")
    if not _user_can_see_thread(user, t):
        raise HTTPException(404, "线程不存在")
    return t


@router.post("/{thread_id}/read")
def mark_read(thread_id: int, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    db.execute(
        "INSERT INTO thread_reads (thread_id, user_id) VALUES (%s, %s) "
        "ON CONFLICT (thread_id, user_id) DO UPDATE SET read_at = now()",
        (thread_id, user["id"]),
    )
    return {"ok": True}


@router.post("/{thread_id}/unread")
def mark_unread(thread_id: int, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    db.execute(
        "DELETE FROM thread_reads WHERE thread_id=%s AND user_id=%s",
        (thread_id, user["id"]),
    )
    return {"ok": True}


@router.post("/{thread_id}/archive")
def archive(thread_id: int, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    db.execute("UPDATE threads SET status='archived' WHERE id=%s", (thread_id,))
    return {"ok": True}


@router.post("/{thread_id}/unarchive")
def unarchive(thread_id: int, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    db.execute("UPDATE threads SET status='inbox' WHERE id=%s", (thread_id,))
    return {"ok": True}


@router.delete("/{thread_id}")
def trash(thread_id: int, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    db.execute("UPDATE threads SET status='trash' WHERE id=%s", (thread_id,))
    return {"ok": True}


@router.post("/{thread_id}/flag")
def toggle_flag(thread_id: int, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    row = db.execute_returning(
        "UPDATE threads SET flagged=NOT COALESCE(flagged,false) WHERE id=%s RETURNING flagged",
        (thread_id,),
    )
    return {"ok": True, "flagged": row["flagged"] if row else None}


@router.post("/{thread_id}/pin")
def pin(thread_id: int, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    db.execute("UPDATE threads SET pinned=true, pinned_at=now() WHERE id=%s", (thread_id,))
    return {"ok": True, "pinned": True}


@router.post("/{thread_id}/unpin")
def unpin(thread_id: int, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    db.execute("UPDATE threads SET pinned=false, pinned_at=NULL WHERE id=%s", (thread_id,))
    return {"ok": True, "pinned": False}


class SnoozeIn(BaseModel):
    snoozed_until: datetime


@router.post("/{thread_id}/snooze")
def snooze(thread_id: int, body: SnoozeIn, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    if body.snoozed_until <= datetime.now(body.snoozed_until.tzinfo):
        raise HTTPException(400, "暂停时间必须在未来")
    db.execute("UPDATE threads SET snoozed_until=%s WHERE id=%s", (body.snoozed_until, thread_id))
    return {"ok": True, "snoozed_until": body.snoozed_until}


@router.post("/{thread_id}/unsnooze")
def unsnooze(thread_id: int, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    db.execute("UPDATE threads SET snoozed_until=NULL WHERE id=%s", (thread_id,))
    return {"ok": True, "snoozed_until": None}


class ReplyIn(BaseModel):
    sender_id: int
    to: list[str]
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: Optional[str] = None
    body_text: str
    body_html: Optional[str] = None
    attachment_ids: list[int] = Field(default_factory=list)
    include_signature: bool = True
    delay_send_seconds: int = Field(default=0, ge=0, le=300)


def _reply_subject(subject: str | None) -> str:
    value = (subject or "").strip() or "(no subject)"
    return value if _REPLY_PREFIX_RE.match(value) else f"Re: {value}"


@router.post("/{thread_id}/reply")
def reply(thread_id: int, body: ReplyIn, user: dict = Depends(authmod.get_current_user)):
    t = _assert_thread_access(thread_id, user)

    last = db.fetchone(
        "SELECT message_id, in_reply_to, references_chain, subject "
        "FROM messages WHERE thread_id=%s ORDER BY received_at DESC LIMIT 1",
        (thread_id,),
    )
    in_reply_to = last["message_id"] if last else None
    references = (last["references_chain"] or []) if last else []
    if last and last["message_id"]:
        references.append(last["message_id"])
    references = list(dict.fromkeys(filter(None, references)))

    subject = _reply_subject(body.subject or ((last["subject"] or t["subject_initial"]) if last else t["subject_initial"]))

    if body.delay_send_seconds > 0:
        scheduled_for = datetime.now(timezone.utc) + timedelta(seconds=body.delay_send_seconds)
        return queue_send(
            user_id=user["id"],
            thread_id=thread_id,
            sender_id=body.sender_id,
            to=body.to,
            cc=body.cc,
            bcc=body.bcc,
            subject=subject,
            body_text=body.body_text,
            body_html=body.body_html,
            scheduled_for=scheduled_for,
            in_reply_to=in_reply_to,
            references=references,
            attachment_ids=body.attachment_ids,
        )

    result = send_outbound_message(
        thread_id=thread_id,
        user_id=user["id"],
        sender_id=body.sender_id,
        to=body.to,
        cc=body.cc,
        bcc=body.bcc,
        subject=subject,
        body_text=body.body_text,
        body_html=body.body_html,
        in_reply_to=in_reply_to,
        references=references,
        attachment_ids=body.attachment_ids,
        event_action="reply_sent",
    )
    if result.get("sent_status") == "failed":
        raise HTTPException(500, f"投递失败: {result.get('sent_error')}")
    return result


@router.post("/{thread_id}/cancel-undo-send/{send_id}")
def cancel_undo_send(thread_id: int, send_id: int, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    return cancel_scheduled_send(send_id=send_id, user_id=user["id"], thread_id=thread_id)


@router.post("/{thread_id}/recall/{msg_id}")
def recall_message(thread_id: int, msg_id: int, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    msg = db.fetchone(
        "SELECT id FROM messages WHERE id=%s AND thread_id=%s AND direction='out'",
        (msg_id, thread_id),
    )
    if not msg:
        raise HTTPException(404, "已发送邮件不存在")
    db.execute(
        "INSERT INTO events (user_id, action, target_type, target_id, payload) "
        "VALUES (%s, 'recall_requested', 'message', %s, %s::jsonb)",
        (user["id"], msg_id, json.dumps({"thread_id": thread_id}, ensure_ascii=False)),
    )
    return {"ok": True, "notice_sent": False}


@router.get("/{thread_id}/attachment/{att_id}")
def download_attachment(thread_id: int, att_id: int, user: dict = Depends(authmod.get_current_user)):
    _assert_thread_access(thread_id, user)
    a = db.fetchone(
        "SELECT a.* FROM attachments a JOIN messages m ON m.id=a.message_id "
        "WHERE a.id=%s AND m.thread_id=%s",
        (att_id, thread_id),
    )
    if not a or not a["disk_path"]:
        raise HTTPException(404, "附件不存在")
    return FileResponse(
        a["disk_path"],
        filename=a["filename"] or f"attachment_{att_id}",
        media_type=a["content_type"] or "application/octet-stream",
    )
