import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from .. import auth as authmod, db
from ..mail_send import clean_filename, upload_path_for

router = APIRouter(prefix="/api/attachments", tags=["attachments"])

MAX_UPLOAD_BYTES = int(os.environ.get("MAILHUB_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))


def ensure_schema() -> None:
    if db.fetchone("SELECT to_regclass('public.uploaded_attachments') AS name")["name"]:
        return
    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS uploaded_attachments (
              id BIGSERIAL PRIMARY KEY,
              user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              filename TEXT NOT NULL,
              content_type TEXT,
              size_bytes INT,
              disk_path TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              used_at TIMESTAMPTZ,
              deleted_at TIMESTAMPTZ
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_uploaded_attachments_user "
            "ON uploaded_attachments(user_id, created_at DESC)"
        )
        c.commit()


@router.post("/upload")
async def upload_attachment(request: Request, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    form = await request.form()
    file = form.get("file")
    if not file or not hasattr(file, "filename"):
        raise HTTPException(400, "未收到附件")
    filename = clean_filename(getattr(file, "filename", None))
    data = await file.read()
    size = len(data)
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"附件过大,当前上限 {MAX_UPLOAD_BYTES // 1024 // 1024}MB")
    token = uuid.uuid4().hex
    path = upload_path_for(user["id"], token, filename)
    with open(path, "wb") as f:
        f.write(data)
    row = db.execute_returning(
        """INSERT INTO uploaded_attachments (user_id, filename, content_type, size_bytes, disk_path)
           VALUES (%s,%s,%s,%s,%s)
           RETURNING id, filename, content_type, size_bytes, created_at""",
        (user["id"], filename, getattr(file, "content_type", None), size, str(path)),
    )
    return {
        "id": row["id"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "size": row["size_bytes"],
        "size_bytes": row["size_bytes"],
        "type": "attachment",
        "created_at": row["created_at"],
    }


@router.get("/{attachment_id}/download")
def download_uploaded_attachment(attachment_id: int, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    row = db.fetchone(
        "SELECT filename, content_type, disk_path FROM uploaded_attachments "
        "WHERE id=%s AND user_id=%s AND deleted_at IS NULL",
        (attachment_id, user["id"]),
    )
    if not row or not os.path.exists(row["disk_path"]):
        raise HTTPException(404, "附件不存在")
    return FileResponse(
        row["disk_path"],
        filename=row["filename"],
        media_type=row["content_type"] or "application/octet-stream",
    )


@router.delete("/{attachment_id}")
def delete_uploaded_attachment(attachment_id: int, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    row = db.execute_returning(
        """UPDATE uploaded_attachments
           SET deleted_at=now()
           WHERE id=%s AND user_id=%s AND deleted_at IS NULL
           RETURNING id, disk_path, used_at""",
        (attachment_id, user["id"]),
    )
    if not row:
        raise HTTPException(404, "附件不存在")
    if not row.get("used_at") and row.get("disk_path") and os.path.exists(row["disk_path"]):
        try:
            os.remove(row["disk_path"])
        except OSError:
            pass
    return {"ok": True}
