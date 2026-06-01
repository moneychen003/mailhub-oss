from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth as authmod, db
from ..send_queue import queue_send
from .threads import _assert_thread_access, _reply_subject

router = APIRouter(prefix="/api/scheduled", tags=["scheduled"])


class ScheduledIn(BaseModel):
    thread_id: int
    sender_id: int
    to: list[str]
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: Optional[str] = None
    body_text: str = ""
    body_html: Optional[str] = None
    scheduled_for: datetime
    attachment_ids: list[int] = Field(default_factory=list)
    include_signature: bool = True


def _reply_refs(thread_id: int) -> tuple[str | None, list[str], str | None]:
    last = db.fetchone(
        "SELECT message_id, references_chain, subject FROM messages WHERE thread_id=%s ORDER BY received_at DESC LIMIT 1",
        (thread_id,),
    )
    if not last:
        return None, [], None
    refs = list(last["references_chain"] or [])
    if last.get("message_id"):
        refs.append(last["message_id"])
    return last.get("message_id"), list(dict.fromkeys(filter(None, refs))), last.get("subject")


@router.post("")
def schedule_send(body: ScheduledIn, user: dict = Depends(authmod.get_current_user)):
    thread = _assert_thread_access(body.thread_id, user)
    when = body.scheduled_for
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if when <= datetime.now(when.tzinfo):
        raise HTTPException(400, "计划发送时间必须在未来")
    in_reply_to, refs, last_subject = _reply_refs(body.thread_id)
    subject = _reply_subject(body.subject or last_subject or thread.get("subject_initial"))
    return queue_send(
        user_id=user["id"],
        thread_id=body.thread_id,
        sender_id=body.sender_id,
        to=body.to,
        cc=body.cc,
        bcc=body.bcc,
        subject=subject,
        body_text=body.body_text or "",
        body_html=body.body_html,
        scheduled_for=when,
        in_reply_to=in_reply_to,
        references=refs,
        attachment_ids=body.attachment_ids,
    )
