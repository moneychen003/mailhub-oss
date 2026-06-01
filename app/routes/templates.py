from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth as authmod, db

router = APIRouter(prefix="/api/templates", tags=["templates"])

BUILTIN_TEMPLATES = [
    {"id": None, "name": "收到,稍后处理", "content": "<p>收到,我先看一下,稍后回复你。</p>"},
    {"id": None, "name": "请补充信息", "content": "<p>你好,麻烦补充一下相关信息,我确认后再处理。</p>"},
    {"id": None, "name": "确认完成", "content": "<p>已确认,这边已经处理完成。谢谢。</p>"},
]


def ensure_schema() -> None:
    if db.fetchone("SELECT to_regclass('public.reply_templates') AS name")["name"]:
        return
    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS reply_templates (
              id BIGSERIAL PRIMARY KEY,
              user_id INT REFERENCES users(id) ON DELETE CASCADE,
              name TEXT NOT NULL,
              content TEXT NOT NULL,
              active BOOLEAN NOT NULL DEFAULT true,
              use_count INT NOT NULL DEFAULT 0,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_reply_templates_active "
            "ON reply_templates(user_id, active, updated_at DESC)"
        )
        c.commit()


class TemplateIn(BaseModel):
    name: str
    content: str


@router.get("")
def list_templates(user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    rows = db.fetchall(
        """SELECT id, name, content, use_count, updated_at
           FROM reply_templates
           WHERE active=true AND (user_id IS NULL OR user_id=%s)
           ORDER BY user_id NULLS FIRST, use_count DESC, updated_at DESC, id DESC
           LIMIT 50""",
        (user["id"],),
    )
    return rows or BUILTIN_TEMPLATES


@router.post("")
def create_template(body: TemplateIn, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    row = db.execute_returning(
        """INSERT INTO reply_templates (user_id, name, content, updated_at)
           VALUES (%s,%s,%s,now())
           RETURNING id, name, content, use_count, updated_at""",
        (user["id"], body.name.strip(), body.content),
    )
    return row


@router.put("/{template_id}")
def update_template(template_id: int, body: TemplateIn, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    row = db.execute_returning(
        """UPDATE reply_templates
           SET name=%s, content=%s, updated_at=now()
           WHERE id=%s AND user_id=%s AND active=true
           RETURNING id, name, content, use_count, updated_at""",
        (body.name.strip(), body.content, template_id, user["id"]),
    )
    if not row:
        raise HTTPException(404, "模板不存在")
    return row


@router.delete("/{template_id}")
def delete_template(template_id: int, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    row = db.execute_returning(
        """UPDATE reply_templates
           SET active=false, updated_at=now()
           WHERE id=%s AND user_id=%s AND active=true
           RETURNING id""",
        (template_id, user["id"]),
    )
    if not row:
        raise HTTPException(404, "模板不存在")
    return {"ok": True}


@router.post("/{template_id}/use")
def use_template(template_id: int, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    row = db.execute_returning(
        """UPDATE reply_templates
           SET use_count=use_count+1, updated_at=now()
           WHERE id=%s AND active=true AND (user_id IS NULL OR user_id=%s)
           RETURNING id, use_count""",
        (template_id, user["id"]),
    )
    if not row:
        raise HTTPException(404, "模板不存在")
    return {"ok": True, "id": row["id"], "use_count": row["use_count"]}
