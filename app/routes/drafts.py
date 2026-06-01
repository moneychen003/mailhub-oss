from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import auth as authmod, db
from .threads import _assert_thread_access

router = APIRouter(prefix="/api/drafts", tags=["drafts"])


def ensure_schema() -> None:
    if db.fetchone("SELECT to_regclass('public.drafts') AS name")["name"]:
        return
    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS drafts (
              id BIGSERIAL PRIMARY KEY,
              user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              thread_id BIGINT REFERENCES threads(id) ON DELETE CASCADE,
              sender_id INT REFERENCES senders(id),
              to_emails CITEXT[] NOT NULL DEFAULT '{}',
              cc_emails CITEXT[] NOT NULL DEFAULT '{}',
              bcc_emails CITEXT[] NOT NULL DEFAULT '{}',
              subject TEXT,
              body_text TEXT,
              body_html TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              UNIQUE(user_id, thread_id)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_drafts_user_updated ON drafts(user_id, updated_at DESC)")
        c.commit()


class DraftIn(BaseModel):
    thread_id: int
    sender_id: Optional[int] = None
    to_emails: list[str] = Field(default_factory=list)
    cc_emails: list[str] = Field(default_factory=list)
    bcc_emails: list[str] = Field(default_factory=list)
    subject: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None


@router.get("")
def list_drafts(thread_id: Optional[int] = Query(None), user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    params: list = [user["id"]]
    where = ["user_id=%s"]
    if thread_id is not None:
        _assert_thread_access(thread_id, user)
        where.append("thread_id=%s")
        params.append(thread_id)
    return db.fetchall(
        f"""SELECT id, thread_id, sender_id, to_emails::text[] AS to_emails,
                   cc_emails::text[] AS cc_emails, bcc_emails::text[] AS bcc_emails,
                   subject, body_text, body_html, created_at, updated_at
            FROM drafts
            WHERE {' AND '.join(where)}
            ORDER BY updated_at DESC
            LIMIT 50""",
        tuple(params),
    )


@router.post("")
def upsert_draft(body: DraftIn, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    _assert_thread_access(body.thread_id, user)
    row = db.execute_returning(
        """INSERT INTO drafts
           (user_id, thread_id, sender_id, to_emails, cc_emails, bcc_emails,
            subject, body_text, body_html, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
           ON CONFLICT (user_id, thread_id) DO UPDATE SET
             sender_id=EXCLUDED.sender_id,
             to_emails=EXCLUDED.to_emails,
             cc_emails=EXCLUDED.cc_emails,
             bcc_emails=EXCLUDED.bcc_emails,
             subject=EXCLUDED.subject,
             body_text=EXCLUDED.body_text,
             body_html=EXCLUDED.body_html,
             updated_at=now()
           RETURNING id, thread_id, sender_id, updated_at""",
        (
            user["id"],
            body.thread_id,
            body.sender_id,
            body.to_emails,
            body.cc_emails,
            body.bcc_emails,
            body.subject,
            body.body_text,
            body.body_html,
        ),
    )
    return row


@router.put("/{draft_id}")
def update_draft(draft_id: int, body: DraftIn, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    _assert_thread_access(body.thread_id, user)
    row = db.execute_returning(
        """UPDATE drafts SET
             thread_id=%s, sender_id=%s, to_emails=%s, cc_emails=%s, bcc_emails=%s,
             subject=%s, body_text=%s, body_html=%s, updated_at=now()
           WHERE id=%s AND user_id=%s
           RETURNING id, thread_id, sender_id, updated_at""",
        (
            body.thread_id,
            body.sender_id,
            body.to_emails,
            body.cc_emails,
            body.bcc_emails,
            body.subject,
            body.body_text,
            body.body_html,
            draft_id,
            user["id"],
        ),
    )
    if not row:
        raise HTTPException(404, "草稿不存在")
    return row


@router.delete("/{draft_id}")
def delete_draft(draft_id: int, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    row = db.execute_returning(
        "DELETE FROM drafts WHERE id=%s AND user_id=%s RETURNING id",
        (draft_id, user["id"]),
    )
    if not row:
        raise HTTPException(404, "草稿不存在")
    return {"ok": True}
