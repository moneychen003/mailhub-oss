from datetime import datetime
from typing import Any

from fastapi import HTTPException

from . import db
from .mail_send import send_outbound_message

_schema_ready = False


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    if db.fetchone("SELECT to_regclass('public.scheduled_sends') AS name")["name"]:
        _schema_ready = True
        return
    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_sends (
              id BIGSERIAL PRIMARY KEY,
              user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              thread_id BIGINT REFERENCES threads(id) ON DELETE CASCADE,
              sender_id INT NOT NULL REFERENCES senders(id),
              to_emails CITEXT[] NOT NULL DEFAULT '{}',
              cc_emails CITEXT[] NOT NULL DEFAULT '{}',
              bcc_emails CITEXT[] NOT NULL DEFAULT '{}',
              subject TEXT NOT NULL,
              body_text TEXT NOT NULL DEFAULT '',
              body_html TEXT,
              in_reply_to TEXT,
              references_chain TEXT[] NOT NULL DEFAULT '{}',
              attachment_ids BIGINT[] NOT NULL DEFAULT '{}',
              scheduled_for TIMESTAMPTZ NOT NULL,
              status TEXT NOT NULL DEFAULT 'queued',
              sent_message_id BIGINT REFERENCES messages(id) ON DELETE SET NULL,
              error TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              sent_at TIMESTAMPTZ,
              cancelled_at TIMESTAMPTZ
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_sends_due "
            "ON scheduled_sends(status, scheduled_for) WHERE status='queued'"
        )
        c.commit()
    _schema_ready = True


def queue_send(
    *,
    user_id: int,
    thread_id: int,
    sender_id: int,
    to: list[str],
    cc: list[str] | None,
    bcc: list[str] | None,
    subject: str,
    body_text: str,
    body_html: str | None,
    scheduled_for: datetime,
    in_reply_to: str | None = None,
    references: list[str] | None = None,
    attachment_ids: list[int] | None = None,
) -> dict[str, Any]:
    ensure_schema()
    row = db.execute_returning(
        """INSERT INTO scheduled_sends
           (user_id, thread_id, sender_id, to_emails, cc_emails, bcc_emails,
            subject, body_text, body_html, in_reply_to, references_chain,
            attachment_ids, scheduled_for, status, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued',now())
           RETURNING id, status, scheduled_for""",
        (
            user_id,
            thread_id,
            sender_id,
            to,
            cc or [],
            bcc or [],
            subject,
            body_text or "",
            body_html,
            in_reply_to,
            references or [],
            attachment_ids or [],
            scheduled_for,
        ),
    )
    return {"id": row["id"], "scheduled_send_id": row["id"], "status": row["status"], "scheduled_for": row["scheduled_for"]}


def cancel_scheduled_send(*, send_id: int, user_id: int, thread_id: int) -> dict[str, Any]:
    ensure_schema()
    row = db.execute_returning(
        """UPDATE scheduled_sends
           SET status='cancelled', cancelled_at=now(), updated_at=now()
           WHERE id=%s AND user_id=%s AND thread_id=%s AND status='queued'
           RETURNING id, status""",
        (send_id, user_id, thread_id),
    )
    if not row:
        raise HTTPException(404, "排程不存在或已经发送")
    return {"ok": True, "id": row["id"], "status": row["status"]}


def process_due_scheduled_sends(limit: int = 10) -> int:
    ensure_schema()
    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            """SELECT *
               FROM scheduled_sends
               WHERE status='queued' AND scheduled_for <= now()
               ORDER BY scheduled_for ASC, id ASC
               LIMIT %s
               FOR UPDATE SKIP LOCKED""",
            (limit,),
        )
        rows = cur.fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            cur.execute("UPDATE scheduled_sends SET status='sending', updated_at=now() WHERE id=ANY(%s)", (ids,))
        c.commit()

    sent_count = 0
    for row in rows:
        try:
            result = send_outbound_message(
                thread_id=row["thread_id"],
                user_id=row["user_id"],
                sender_id=row["sender_id"],
                to=list(row["to_emails"] or []),
                cc=list(row["cc_emails"] or []),
                bcc=list(row["bcc_emails"] or []),
                subject=row["subject"],
                body_text=row["body_text"] or "",
                body_html=row["body_html"],
                in_reply_to=row["in_reply_to"],
                references=list(row["references_chain"] or []),
                attachment_ids=list(row["attachment_ids"] or []),
                event_action="scheduled_sent",
            )
            if result.get("sent_status") == "sent":
                db.execute(
                    """UPDATE scheduled_sends
                       SET status='sent', sent_at=now(), updated_at=now(), sent_message_id=%s, error=NULL
                       WHERE id=%s""",
                    (result["id"], row["id"]),
                )
                sent_count += 1
            else:
                db.execute(
                    """UPDATE scheduled_sends
                       SET status='failed', updated_at=now(), error=%s, sent_message_id=%s
                       WHERE id=%s""",
                    (result.get("sent_error") or "send failed", result.get("id"), row["id"]),
                )
        except Exception as e:
            db.execute(
                "UPDATE scheduled_sends SET status='failed', updated_at=now(), error=%s WHERE id=%s",
                (repr(e), row["id"]),
            )
    return sent_count
