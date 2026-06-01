from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth as authmod, db
from .threads import _assert_thread_access

router = APIRouter(prefix="/api/folders", tags=["folders"])

_schema_ready = False


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS folders (
              id BIGSERIAL PRIMARY KEY,
              user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              name TEXT NOT NULL,
              color TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              UNIQUE(user_id, name)
            )
            """
        )
        cur.execute("ALTER TABLE folders ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id) ON DELETE CASCADE")
        cur.execute("ALTER TABLE folders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()")
        cur.execute(
            """
            SELECT EXISTS (
              SELECT 1
              FROM information_schema.columns
              WHERE table_schema='public'
                AND table_name='folders'
                AND column_name='created_by'
            ) AS has_created_by
            """
        )
        has_created_by = bool(cur.fetchone()["has_created_by"])
        if has_created_by:
            cur.execute(
                """
                UPDATE folders
                SET user_id = COALESCE(created_by, (SELECT id FROM users ORDER BY id LIMIT 1))
                WHERE user_id IS NULL
                """
            )
        else:
            cur.execute(
                """
                UPDATE folders
                SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1)
                WHERE user_id IS NULL
                """
            )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS thread_folders (
              thread_id BIGINT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
              folder_id BIGINT NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
              user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              PRIMARY KEY(thread_id, folder_id)
            )
            """
        )
        cur.execute("ALTER TABLE thread_folders ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id) ON DELETE CASCADE")
        cur.execute(
            """
            UPDATE thread_folders tf
            SET user_id = f.user_id
            FROM folders f
            WHERE tf.folder_id = f.id AND tf.user_id IS NULL
            """
        )
        c.commit()
    _schema_ready = True


class FolderIn(BaseModel):
    name: str
    color: Optional[str] = None


class MoveIn(BaseModel):
    thread_id: int
    folder_id: Optional[int] = None


@router.get("")
def list_folders(user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    return db.fetchall(
        """
        SELECT f.id, f.name, f.color, f.created_at, f.updated_at,
               count(tf.thread_id)::int AS count
        FROM folders f
        LEFT JOIN thread_folders tf ON tf.folder_id = f.id AND tf.user_id = f.user_id
        WHERE f.user_id = %s
        GROUP BY f.id
        ORDER BY lower(f.name)
        """,
        (user["id"],),
    )


@router.post("")
def create_folder(body: FolderIn, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "文件夹名不能为空")
    if len(name) > 80:
        raise HTTPException(400, "文件夹名过长")
    existing = db.fetchone(
        "SELECT id FROM folders WHERE user_id=%s AND lower(name)=lower(%s)",
        (user["id"], name),
    )
    if existing:
        row = db.execute_returning(
            """
            UPDATE folders
            SET color=COALESCE(%s, color), updated_at=now()
            WHERE id=%s AND user_id=%s
            RETURNING id, name, color, created_at, updated_at
            """,
            (body.color, existing["id"], user["id"]),
        )
        return row
    row = db.execute_returning(
        """
        INSERT INTO folders (user_id, name, color)
        VALUES (%s, %s, %s)
        RETURNING id, name, color, created_at, updated_at
        """,
        (user["id"], name, body.color),
    )
    return row


@router.post("/move")
def move_thread(body: MoveIn, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    _assert_thread_access(body.thread_id, user)

    if body.folder_id is None:
        db.execute(
            "DELETE FROM thread_folders WHERE user_id=%s AND thread_id=%s",
            (user["id"], body.thread_id),
        )
        return {"ok": True, "folder_id": None}

    folder = db.fetchone(
        "SELECT id FROM folders WHERE id=%s AND user_id=%s",
        (body.folder_id, user["id"]),
    )
    if not folder:
        raise HTTPException(404, "文件夹不存在")

    # Current UI treats a thread as being in at most one custom folder for a user.
    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            "DELETE FROM thread_folders WHERE user_id=%s AND thread_id=%s",
            (user["id"], body.thread_id),
        )
        cur.execute(
            """
            INSERT INTO thread_folders (thread_id, folder_id, user_id)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (body.thread_id, body.folder_id, user["id"]),
        )
        c.commit()
    return {"ok": True, "folder_id": body.folder_id}


@router.delete("/{folder_id}")
def delete_folder(folder_id: int, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    db.execute("DELETE FROM folders WHERE id=%s AND user_id=%s", (folder_id, user["id"]))
    return {"ok": True}
