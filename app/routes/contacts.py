from fastapi import APIRouter, Depends

from .. import auth as authmod, db

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


def _visibility_clause(user: dict, table_alias: str = "t") -> tuple[str, list]:
    if user.get("role") == "admin":
        return "", []
    user_email = (user.get("email") or "").lower()
    if not user_email:
        return " AND false", []
    return (
        f" AND EXISTS (SELECT 1 FROM unnest({table_alias}.participants) p WHERE lower(p) = %s)",
        [user_email],
    )


@router.get("/{email}")
def contact_detail(email: str, user: dict = Depends(authmod.get_current_user)):
    normalized = email.strip().lower()
    visible, params = _visibility_clause(user, "t")
    row = db.fetchone(
        f"""
        SELECT
          %s AS email,
          count(*) FILTER (WHERE m.direction='in' AND lower(m.from_email::text)=%s)::int AS total_in,
          count(*) FILTER (
            WHERE m.direction='out'
              AND (
                EXISTS (SELECT 1 FROM unnest(m.to_emails::text[]) e WHERE lower(e)=%s)
                OR EXISTS (SELECT 1 FROM unnest(m.cc_emails::text[]) e WHERE lower(e)=%s)
              )
          )::int AS total_out,
          count(*) FILTER (
            WHERE m.direction='in'
              AND lower(m.from_email::text)=%s
              AND m.received_at >= now() - interval '30 days'
          )::int AS recent_30d,
          min(m.received_at) AS first_seen_at,
          max(m.received_at) AS last_seen_at,
          array_remove(array_agg(DISTINCT NULLIF(m.from_name, '')), NULL) AS names
        FROM messages m
        JOIN threads t ON t.id = m.thread_id
        WHERE (
          lower(m.from_email::text)=%s
          OR EXISTS (SELECT 1 FROM unnest(m.to_emails::text[]) e WHERE lower(e)=%s)
          OR EXISTS (SELECT 1 FROM unnest(m.cc_emails::text[]) e WHERE lower(e)=%s)
        )
        {visible}
        """,
        tuple(
            [
                normalized,
                normalized,
                normalized,
                normalized,
                normalized,
                normalized,
                normalized,
                normalized,
            ]
            + params
        ),
    )
    total_in = int(row.get("total_in") or 0) if row else 0
    total_out = int(row.get("total_out") or 0) if row else 0
    if not row or (total_in + total_out) == 0:
        return {"contact": None}
    row["total"] = total_in + total_out
    return {"contact": row}
