from fastapi import APIRouter, Depends
from .. import db, auth as authmod
from .threads import ensure_thread_state_schema

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/summary")
def summary(user: dict = Depends(authmod.get_current_user)):
    ensure_thread_state_schema()
    active_inbox = "status='inbox' AND (snoozed_until IS NULL OR snoozed_until <= now())"
    return {
        "total_threads": db.fetchone("SELECT count(*) AS c FROM threads")["c"],
        "inbox_threads": db.fetchone(f"SELECT count(*) AS c FROM threads WHERE {active_inbox}")["c"],
        "inbox_visible_threads": db.fetchone(
            f"SELECT count(*) AS c FROM threads WHERE {active_inbox} "
            "AND COALESCE(ai_priority, 'normal') NOT IN ('spam','low') "
            "AND COALESCE(ai_category, '') <> 'marketing'"
        )["c"],
        "unread_threads": db.fetchone(
            "SELECT count(*) AS c FROM threads t WHERE t.status='inbox' "
            "AND (t.snoozed_until IS NULL OR t.snoozed_until <= now()) "
            "AND NOT EXISTS (SELECT 1 FROM thread_reads tr WHERE tr.thread_id=t.id AND tr.user_id=%s)",
            (user["id"],),
        )["c"],
        "urgent_threads": db.fetchone(
            f"SELECT count(*) AS c FROM threads WHERE {active_inbox} AND ai_priority='urgent'"
        )["c"],
        "high_threads": db.fetchone(
            f"SELECT count(*) AS c FROM threads WHERE {active_inbox} AND ai_priority='high'"
        )["c"],
        "billing_pending": db.fetchone(
            f"SELECT count(*) AS c FROM threads WHERE {active_inbox} "
            "AND ai_category IN ('billing','finance') AND ai_priority IN ('urgent','high')"
        )["c"],
        "shipping_urgent": db.fetchone(
            f"SELECT count(*) AS c FROM threads WHERE {active_inbox} AND ai_category='shipping'"
        )["c"],
        "security_alerts": db.fetchone(
            f"SELECT count(*) AS c FROM threads WHERE {active_inbox} "
            "AND ai_category IN ('security','system') AND ai_priority IN ('urgent','high')"
        )["c"],
        "due_today": db.fetchone(
            f"SELECT count(*) AS c FROM threads WHERE {active_inbox} "
            "AND due_at IS NOT NULL AND due_at <= now() + interval '24 hours'"
        )["c"],
        "sources": db.fetchall(
            f"""
            SELECT COALESCE(NULLIF(source,''),'unknown') AS source, count(*)::int AS c
            FROM threads
            WHERE {active_inbox}
            GROUP BY COALESCE(NULLIF(source,''),'unknown')
            ORDER BY c DESC, source
            """
        ),
        "total_messages_in": db.fetchone("SELECT count(*) AS c FROM messages WHERE direction='in'")["c"],
        "total_messages_out": db.fetchone("SELECT count(*) AS c FROM messages WHERE direction='out'")["c"],
        "due_soon": db.fetchall(
            "SELECT id, subject_initial, due_at FROM threads "
            "WHERE status='inbox' AND (snoozed_until IS NULL OR snoozed_until <= now()) "
            "AND due_at IS NOT NULL AND due_at > now() AND due_at < now() + interval '7 days' "
            "ORDER BY due_at LIMIT 5"
        ),
    }
