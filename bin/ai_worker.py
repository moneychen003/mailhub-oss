#!/opt/mailhub/venv/bin/python
"""
AI classifier worker. Polls threads with ai_classified_at IS NULL,
calls configured AI endpoint (OpenAI or Anthropic format), and updates
threads with priority/category/summary/action/due_at. Pushes TG if priority
matches threshold.

Run as systemd service.
"""
import os
import sys
import time
import json
import signal
import logging
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.send_queue import process_due_scheduled_sends

load_dotenv("/opt/mailhub/.env")
load_dotenv(ROOT / ".env")
DATABASE_URL = os.environ["DATABASE_URL"]
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:3024")

LOG_DIR = os.environ.get("LOG_DIR", "/opt/mailhub/logs")
Path(LOG_DIR).mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(f"{LOG_DIR}/ai_worker.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("ai_worker")

POLL_INTERVAL = 5  # seconds
BATCH_SIZE = 5
PRIORITY_RANK = {"spam": 0, "low": 1, "normal": 2, "high": 3, "urgent": 4}

SYSTEM_PROMPT_DEFAULT = """你是邮件分类助手。读一封邮件,严格返回一个 json 对象 (response_format=json_object),不要任何 markdown 围栏或解释,字段:
- priority: "urgent" | "high" | "normal" | "low" | "spam"
- category: "billing"|"order"|"support"|"marketing"|"personal"|"system"|"shipping"|"finance"|"other"
- summary: 中文,1 句话,<=80 字
- action: 中文,建议动作,<=40 字 (如 "无需回复" / "5月4日前需付款" / "请确认收货")
- due_at: ISO8601 (YYYY-MM-DDTHH:MM:SS) 或 null,如果邮件提到具体截止日期/付款日/到期日就提取

优先级判断标准:
- urgent: 当天必须处理,迟则有具体损失 (仓储费/逾期罚款/服务停用)
- high: 7天内必须处理,涉及钱/合同/关键操作
- normal: 正常对话/订单更新/回执
- low: 信息性通知/不需操作
- spam: 营销/推广/钓鱼
"""


def db_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def ensure_rules_schema():
    with db_conn() as c, c.cursor() as cur:
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


def get_ai_config():
    with db_conn() as c, c.cursor() as cur:
        cur.execute("SELECT provider, endpoint, api_key, model, system_prompt, enabled FROM ai_config WHERE id=1")
        return cur.fetchone()


def get_tg_config():
    with db_conn() as c, c.cursor() as cur:
        cur.execute("SELECT bot_token, chat_id, push_min_priority, enabled FROM tg_config WHERE id=1")
        return cur.fetchone()


def fetch_unprocessed_threads(limit: int) -> list[dict]:
    with db_conn() as c, c.cursor() as cur:
        cur.execute(
            """SELECT t.id, t.subject_initial, t.participants
               FROM threads t
               WHERE t.ai_classified_at IS NULL
                 AND t.message_count > 0
                 AND NOT EXISTS (
                   SELECT 1 FROM ai_jobs j
                   WHERE j.thread_id=t.id
                     AND j.status='running'
                     AND j.created_at > now() - interval '10 minutes'
                 )
                 AND NOT EXISTS (
                   SELECT 1 FROM ai_jobs j
                   WHERE j.thread_id=t.id
                     AND j.status='failed'
                     AND j.finished_at > now() - interval '15 minutes'
                 )
               ORDER BY t.last_message_at DESC NULLS LAST
               LIMIT %s""",
            (limit,),
        )
        return cur.fetchall()


def fetch_thread_messages(thread_id: int) -> list[dict]:
    with db_conn() as c, c.cursor() as cur:
        cur.execute(
            """SELECT direction, subject, from_email, from_name, to_emails, snippet, body_text, body_html, received_at
               FROM messages WHERE thread_id=%s ORDER BY received_at ASC""",
            (thread_id,),
        )
        return cur.fetchall()


def fetch_matching_rule(messages: list[dict]) -> dict | None:
    with db_conn() as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT id, scope, value, force_priority
            FROM classification_rules
            WHERE active=true
            ORDER BY updated_at DESC, id DESC
            """
        )
        rules = cur.fetchall()
    if not rules:
        return None

    from_emails = set()
    from_domains = set()
    subjects = []
    for msg in messages:
        email = str(msg.get("from_email") or "").lower()
        if email:
            from_emails.add(email)
            if "@" in email:
                from_domains.add(email.split("@", 1)[1])
        subjects.append(str(msg.get("subject") or "").lower())

    for rule in rules:
        scope = rule.get("scope")
        value = str(rule.get("value") or "").lower()
        if scope == "from_email" and value in from_emails:
            return rule
        if scope == "from_domain" and value in from_domains:
            return rule
        if scope == "subject_keyword" and any(value in subject for subject in subjects):
            return rule
    return None


def build_user_prompt(messages: list[dict]) -> str:
    parts = []
    for i, m in enumerate(messages[-3:]):  # 只看最近 3 封省 token
        body = (m.get("body_text") or m.get("snippet") or "")[:2000]
        parts.append(
            f"--- 邮件 {i+1} ({m['direction']}) ---\n"
            f"From: {m.get('from_name') or ''} <{m.get('from_email')}>\n"
            f"To: {', '.join(m.get('to_emails') or [])}\n"
            f"Subject: {m.get('subject')}\n"
            f"Date: {m.get('received_at')}\n\n"
            f"{body}"
        )
    return "\n\n".join(parts)


def call_openai(cfg: dict, system_prompt: str, user_prompt: str) -> tuple[str, dict]:
    """OpenAI-compatible (also Bailian/Qwen/DeepSeek etc)."""
    url = cfg["endpoint"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    r = httpx.post(url, headers=headers, json=body, timeout=60)
    r.raise_for_status()
    data = r.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")}


def call_anthropic(cfg: dict, system_prompt: str, user_prompt: str) -> tuple[str, dict]:
    url = cfg["endpoint"].rstrip("/") + "/v1/messages"
    headers = {
        "x-api-key": cfg["api_key"],
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": cfg["model"],
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt + "\n\n严格返回纯 JSON,不要 markdown 围栏。"}],
        "temperature": 0.2,
    }
    r = httpx.post(url, headers=headers, json=body, timeout=60)
    r.raise_for_status()
    data = r.json()
    content = data["content"][0]["text"]
    usage = data.get("usage", {})
    return content, {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}


def parse_ai_result(raw: str) -> dict:
    s = raw.strip()
    # 去 markdown 围栏
    if s.startswith("```"):
        lines = s.split("\n")
        s = "\n".join(lines[1:-1]) if len(lines) >= 3 else s
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # 尝试找到第一个 { 和最后一个 }
        l, r = s.find("{"), s.rfind("}")
        if l >= 0 and r > l:
            return json.loads(s[l : r + 1])
        raise


def parse_due(due_str) -> datetime | None:
    if not due_str or due_str == "null":
        return None
    try:
        s = str(due_str).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


def push_tg_if_needed(thread_id: int, thread_subject: str, last_from: str, result: dict, tg_cfg: dict | None):
    if not tg_cfg or not tg_cfg.get("enabled") or not tg_cfg.get("bot_token") or not tg_cfg.get("chat_id"):
        return
    min_rank = PRIORITY_RANK.get(tg_cfg.get("push_min_priority", "high"), 3)
    cur_rank = PRIORITY_RANK.get(result.get("priority", "normal"), 2)
    if cur_rank < min_rank:
        return
    icon = {"urgent": "🚨", "high": "❗", "normal": "📨", "low": "💬", "spam": "🗑"}.get(result.get("priority"), "📨")
    due_line = f"\n⏰ 截止: {result['due_at']}" if result.get("due_at") else ""
    text = (
        f"{icon} <b>[{result.get('priority','?').upper()}]</b> {result.get('category','')}\n"
        f"<b>From:</b> {last_from}\n"
        f"<b>主题:</b> {thread_subject or '(no subject)'}\n"
        f"<b>摘要:</b> {result.get('summary','')}\n"
        f"<b>建议:</b> {result.get('action','')}{due_line}\n\n"
        f"{API_BASE_URL}/thread/{thread_id}"
    )
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{tg_cfg['bot_token']}/sendMessage",
            json={
                "chat_id": tg_cfg["chat_id"],
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if r.status_code != 200:
            log.warning("tg push failed status=%s body=%s", r.status_code, r.text[:200])
    except Exception as e:
        log.warning("tg push exception: %s", e)


def classify_thread(thread_id: int, ai_cfg: dict, tg_cfg: dict | None) -> bool:
    msgs = fetch_thread_messages(thread_id)
    if not msgs:
        return False
    subject = msgs[-1].get("subject") or ""
    last_from = f"{msgs[-1].get('from_name') or ''} <{msgs[-1].get('from_email')}>"
    user_prompt = build_user_prompt(msgs)
    system_prompt = ai_cfg.get("system_prompt") or SYSTEM_PROMPT_DEFAULT

    started = datetime.now(timezone.utc)
    job_id = None
    with db_conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO ai_jobs (thread_id, status) VALUES (%s, 'running') RETURNING id",
            (thread_id,),
        )
        job_id = cur.fetchone()["id"]
        c.commit()

    try:
        if ai_cfg["provider"] == "anthropic":
            content, usage = call_anthropic(ai_cfg, system_prompt, user_prompt)
        else:
            content, usage = call_openai(ai_cfg, system_prompt, user_prompt)
        result = parse_ai_result(content)
        priority = result.get("priority", "normal")
        if priority not in PRIORITY_RANK:
            priority = "normal"
        category = result.get("category", "other")
        summary = (result.get("summary") or "")[:500]
        action = (result.get("action") or "")[:200]
        due_at = parse_due(result.get("due_at"))
        rule = fetch_matching_rule(msgs)
        if rule and rule.get("force_priority") in PRIORITY_RANK:
            priority = rule["force_priority"]
            result["priority"] = priority
            result["rule_override"] = {
                "id": rule["id"],
                "scope": rule["scope"],
                "value": rule["value"],
            }

        with db_conn() as c, c.cursor() as cur:
            cur.execute(
                """UPDATE threads SET
                   ai_priority=%s, ai_category=%s, ai_summary=%s, ai_action=%s,
                   ai_model=%s, ai_classified_at=now(), due_at=COALESCE(%s, due_at)
                   WHERE id=%s""",
                (priority, category, summary, action, ai_cfg["model"], due_at, thread_id),
            )
            cur.execute(
                "UPDATE ai_jobs SET status='done', input_tokens=%s, output_tokens=%s, "
                "result=%s, finished_at=now() WHERE id=%s",
                (usage.get("input_tokens"), usage.get("output_tokens"), json.dumps(result), job_id),
            )
            c.commit()
        log.info(
            "classified thread=%s priority=%s category=%s rule=%s",
            thread_id,
            priority,
            category,
            result.get("rule_override"),
        )
        push_tg_if_needed(thread_id, subject, last_from, result, tg_cfg)
        return True
    except Exception as e:
        log.error("classify thread=%s failed: %s\n%s", thread_id, e, traceback.format_exc())
        try:
            with db_conn() as c, c.cursor() as cur:
                cur.execute(
                    "UPDATE ai_jobs SET status='failed', error=%s, finished_at=now() WHERE id=%s",
                    (repr(e), job_id),
                )
                c.commit()
        except Exception:
            pass
        return False


_running = True


def _stop(*_):
    global _running
    _running = False
    log.info("stop signal received")


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def main():
    log.info("AI worker starting")
    ensure_rules_schema()
    while _running:
        try:
            sent = process_due_scheduled_sends(BATCH_SIZE)
            if sent:
                log.info("sent scheduled messages=%s", sent)
            ai_cfg = get_ai_config()
            if not ai_cfg or not ai_cfg["enabled"]:
                time.sleep(POLL_INTERVAL * 2)
                continue
            tg_cfg = get_tg_config()
            threads = fetch_unprocessed_threads(BATCH_SIZE)
            if not threads:
                time.sleep(POLL_INTERVAL)
                continue
            for t in threads:
                if not _running:
                    break
                classify_thread(t["id"], ai_cfg, tg_cfg)
        except Exception as e:
            log.error("worker loop error: %s", e)
            time.sleep(POLL_INTERVAL * 2)
    log.info("AI worker stopped")


if __name__ == "__main__":
    main()
