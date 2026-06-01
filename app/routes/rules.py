import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth as authmod, db
from .threads import _assert_thread_access

router = APIRouter(prefix="/api/rules", tags=["rules"])

VALID_PRIORITIES = {"urgent", "high", "normal", "low", "spam"}
VALID_SCOPES = {"from_email", "from_domain", "subject_keyword"}


def ensure_schema() -> None:
    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS classification_rules (
              id BIGSERIAL PRIMARY KEY,
              user_id INT REFERENCES users(id) ON DELETE CASCADE,
              scope TEXT NOT NULL,
              value TEXT NOT NULL,
              force_priority TEXT NOT NULL,
              created_from_thread_id BIGINT REFERENCES threads(id) ON DELETE SET NULL,
              active BOOLEAN NOT NULL DEFAULT true,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              UNIQUE(user_id, scope, value)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_classification_rules_active "
            "ON classification_rules(user_id, active, scope, value)"
        )
        c.commit()


class QuickRuleIn(BaseModel):
    thread_id: int
    scope: str
    force_priority: str
    keyword: Optional[str] = Field(default=None, max_length=120)
    apply_to_existing: bool = True


class RulePatchIn(BaseModel):
    force_priority: Optional[str] = None
    active: Optional[bool] = None


class RuleIn(BaseModel):
    scope: str
    value: str = Field(max_length=240)
    force_priority: str
    active: bool = True
    apply_to_existing: bool = False


def _rule_target(thread_id: int, scope: str, keyword: str | None) -> str:
    if scope == "subject_keyword":
        value = (keyword or "").strip().lower()
        if not value:
            raise HTTPException(400, "请提供主题关键词")
        return value

    msg = db.fetchone(
        """
        SELECT from_email::text AS from_email
        FROM messages
        WHERE thread_id=%s AND direction='in' AND from_email IS NOT NULL
        ORDER BY received_at DESC, id DESC
        LIMIT 1
        """,
        (thread_id,),
    )
    if not msg or not msg.get("from_email"):
        raise HTTPException(400, "这封邮件没有可用发件人")
    email = msg["from_email"].lower()
    if scope == "from_email":
        return email
    if scope == "from_domain":
        if "@" not in email:
            raise HTTPException(400, "发件人域名无效")
        return email.split("@", 1)[1]
    raise HTTPException(400, "规则范围无效")


def _apply_existing(user: dict, scope: str, value: str, priority: str) -> int:
    visible = ""
    visible_params: list = []
    if user.get("role") != "admin":
        user_email = (user.get("email") or "").lower()
        if not user_email:
            return 0
        visible = "AND EXISTS (SELECT 1 FROM unnest(t.participants) p WHERE lower(p)=%s)"
        visible_params.append(user_email)

    match_params: list = []
    if scope == "from_email":
        match = (
            "EXISTS (SELECT 1 FROM messages m WHERE m.thread_id=t.id "
            "AND lower(m.from_email::text)=%s)"
        )
        match_params.append(value)
    elif scope == "from_domain":
        match = (
            "EXISTS (SELECT 1 FROM messages m WHERE m.thread_id=t.id "
            "AND lower(split_part(m.from_email::text, '@', 2))=%s)"
        )
        match_params.append(value)
    elif scope == "subject_keyword":
        match = (
            "(lower(coalesce(t.subject_initial,'')) LIKE %s OR EXISTS "
            "(SELECT 1 FROM messages m WHERE m.thread_id=t.id AND lower(coalesce(m.subject,'')) LIKE %s))"
        )
        like = f"%{value}%"
        match_params.extend([like, like])
    else:
        return 0

    row = db.execute_returning(
        f"""
        WITH matched AS (
          SELECT t.id
          FROM threads t
          WHERE {match}
          {visible}
        ),
        updated AS (
          UPDATE threads t
          SET ai_priority=%s, ai_classified_at=now()
          FROM matched
          WHERE t.id=matched.id
          RETURNING t.id
        )
        SELECT count(*)::int AS c FROM updated
        """,
        tuple(match_params + visible_params + [priority]),
    )
    return int(row["c"] if row else 0)


@router.post("/quick")
def quick_rule(body: QuickRuleIn, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    _assert_thread_access(body.thread_id, user)
    scope = body.scope
    priority = body.force_priority
    if scope not in VALID_SCOPES:
        raise HTTPException(400, "规则范围无效")
    if priority not in VALID_PRIORITIES:
        raise HTTPException(400, "优先级无效")

    value = _rule_target(body.thread_id, scope, body.keyword)
    rule = db.execute_returning(
        """
        INSERT INTO classification_rules
          (user_id, scope, value, force_priority, created_from_thread_id, active, updated_at)
        VALUES (%s,%s,%s,%s,%s,true,now())
        ON CONFLICT (user_id, scope, value) DO UPDATE
        SET force_priority=EXCLUDED.force_priority,
            created_from_thread_id=EXCLUDED.created_from_thread_id,
            active=true,
            updated_at=now()
        RETURNING id, scope, value, force_priority
        """,
        (user["id"], scope, value, priority, body.thread_id),
    )
    affected = _apply_existing(user, scope, value, priority) if body.apply_to_existing else 0
    db.execute(
        "INSERT INTO events (user_id, action, target_type, target_id, payload) "
        "VALUES (%s, 'rule_quick_created', 'classification_rule', %s, %s::jsonb)",
        (
            user["id"],
            rule["id"],
            json.dumps(
                {
                    "scope": scope,
                    "value": value,
                    "force_priority": priority,
                    "affected_threads": affected,
                }
            ),
        ),
    )
    return {"ok": True, "rule": rule, "affected_threads": affected}


@router.get("")
def list_rules(user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    return db.fetchall(
        """
        SELECT id, scope, value, force_priority, active, created_from_thread_id, created_at, updated_at
        FROM classification_rules
        WHERE user_id=%s
        ORDER BY active DESC, updated_at DESC, id DESC
        """,
        (user["id"],),
    )


@router.post("")
def create_rule(body: RuleIn, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    scope = body.scope
    priority = body.force_priority
    value = body.value.strip().lower()
    if scope not in VALID_SCOPES:
        raise HTTPException(400, "规则范围无效")
    if priority not in VALID_PRIORITIES:
        raise HTTPException(400, "优先级无效")
    if not value:
        raise HTTPException(400, "规则值不能为空")
    rule = db.execute_returning(
        """
        INSERT INTO classification_rules
          (user_id, scope, value, force_priority, active, updated_at)
        VALUES (%s,%s,%s,%s,%s,now())
        ON CONFLICT (user_id, scope, value) DO UPDATE
        SET force_priority=EXCLUDED.force_priority,
            active=EXCLUDED.active,
            updated_at=now()
        RETURNING id, scope, value, force_priority, active, updated_at
        """,
        (user["id"], scope, value, priority, body.active),
    )
    affected = _apply_existing(user, scope, value, priority) if body.apply_to_existing else 0
    db.execute(
        "INSERT INTO events (user_id, action, target_type, target_id, payload) "
        "VALUES (%s, 'rule_created', 'classification_rule', %s, %s::jsonb)",
        (
            user["id"],
            rule["id"],
            json.dumps(
                {
                    "scope": scope,
                    "value": value,
                    "force_priority": priority,
                    "affected_threads": affected,
                }
            ),
        ),
    )
    return {"ok": True, "rule": rule, "affected_threads": affected}


@router.patch("/{rule_id}")
def update_rule(rule_id: int, body: RulePatchIn, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    current = db.fetchone(
        "SELECT id, force_priority, active FROM classification_rules WHERE id=%s AND user_id=%s",
        (rule_id, user["id"]),
    )
    if not current:
        raise HTTPException(404, "规则不存在")
    priority = body.force_priority if body.force_priority is not None else current["force_priority"]
    active = body.active if body.active is not None else current["active"]
    if priority not in VALID_PRIORITIES:
        raise HTTPException(400, "优先级无效")
    row = db.execute_returning(
        """
        UPDATE classification_rules
        SET force_priority=%s, active=%s, updated_at=now()
        WHERE id=%s AND user_id=%s
        RETURNING id, scope, value, force_priority, active, updated_at
        """,
        (priority, active, rule_id, user["id"]),
    )
    return row


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, user: dict = Depends(authmod.get_current_user)):
    ensure_schema()
    db.execute("DELETE FROM classification_rules WHERE id=%s AND user_id=%s", (rule_id, user["id"]))
    return {"ok": True}
