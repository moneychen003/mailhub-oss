#!/opt/mailhub/venv/bin/python
"""
Postfix pipe transport entrypoint. Receives raw email on stdin.
Saves raw .eml to disk, parses minimal fields, inserts into Postgres.

Exit codes follow Postfix conventions (sysexits.h):
  0   = success (mail accepted, delivery done)
  75  = EX_TEMPFAIL (defer, postfix will retry)
  78  = EX_CONFIG (config error; bounce won't help)
"""
import sys
import os
import uuid
import json
import re
import traceback
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, getaddresses, parsedate_to_datetime

import psycopg
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv("/opt/mailhub/.env")
load_dotenv(os.path.join(ROOT, ".env"))

DATABASE_URL = os.environ["DATABASE_URL"]
RAW_DIR = os.environ.get("RAW_DIR", "/opt/mailhub/raw")
LOG_PATH = os.path.join(os.environ.get("LOG_DIR", "/opt/mailhub/logs"), "ingest.log")


def log(msg: str, level: str = "INFO"):
    ts = datetime.now(timezone.utc).isoformat()
    line = f"{ts} [{level}] {msg}\n"
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line)
    except Exception:
        sys.stderr.write(line)


def save_raw(data: bytes) -> str:
    """Save raw email bytes; return absolute path."""
    now = datetime.now(timezone.utc)
    sub = now.strftime("%Y/%m/%d")
    dir_path = os.path.join(RAW_DIR, sub)
    os.makedirs(dir_path, exist_ok=True)
    fname = f"{now.strftime('%H%M%S')}_{uuid.uuid4().hex[:12]}.eml"
    path = os.path.join(dir_path, fname)
    with open(path, "wb") as f:
        f.write(data)
    return path


def strip_brackets(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    if s.startswith("<") and s.endswith(">"):
        return s[1:-1]
    return s


def parse_addresses(value) -> tuple[list[str], list[str]]:
    """Return (emails, display_names)."""
    if not value:
        return [], []
    pairs = getaddresses([str(value)])
    emails = [a.lower() for _, a in pairs if a]
    names = [n for n, _ in pairs]
    return emails, names


def find_or_create_thread(conn, message_id: str | None, in_reply_to: str | None,
                          references: list[str], subject: str | None,
                          from_email: str | None, to_emails: list[str],
                          received_at: datetime) -> int:
    """Return thread_id. Match by In-Reply-To / References. Else create new."""
    candidates = []
    if in_reply_to:
        candidates.append(in_reply_to)
    candidates.extend(references)
    candidates = [c for c in candidates if c]

    if candidates:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT thread_id FROM messages "
                "WHERE message_id = ANY(%s) AND thread_id IS NOT NULL "
                "ORDER BY received_at ASC LIMIT 1",
                (candidates,),
            )
            row = cur.fetchone()
            if row:
                return row[0]

    # New thread
    participants = list({*to_emails, from_email} - {None})
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO threads (subject_initial, participants, first_message_at, last_message_at) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (subject, participants, received_at, received_at),
        )
        return cur.fetchone()[0]


def make_snippet(text: str | None, html: str | None, maxlen: int = 200) -> str:
    if text:
        s = re.sub(r"\s+", " ", text).strip()
    elif html:
        from bs4 import BeautifulSoup
        s = re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" ")).strip()
    else:
        s = ""
    return s[:maxlen]


ISO_2022_JP_MARKERS = (b"\x1b$B", b"\x1b$@", b"\x1b$(B", b"\x1b$(D")


def looks_like_iso_2022_jp(payload: bytes) -> bool:
    return any(marker in payload for marker in ISO_2022_JP_MARKERS)


def decode_text_part(part) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        try:
            return part.get_content()
        except Exception:
            return str(part.get_payload() or "")

    candidates: list[str] = []
    if looks_like_iso_2022_jp(payload):
        candidates.append("iso-2022-jp")

    charset = part.get_content_charset()
    if charset:
        candidates.append(charset)

    candidates.append("utf-8")

    seen = set()
    for charset in candidates:
        charset = charset.lower()
        if charset in seen:
            continue
        seen.add(charset)
        try:
            return payload.decode(charset)
        except (LookupError, UnicodeDecodeError):
            continue

    return payload.decode(candidates[-1], "replace")


def extract_bodies(msg) -> tuple[str | None, str | None, list[dict]]:
    """Return (text, html, attachments_list)."""
    text_parts, html_parts, atts = [], [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        disp = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()

        if disp == "attachment" or (filename and disp != "inline"):
            try:
                payload = part.get_payload(decode=True) or b""
            except Exception:
                payload = b""
            atts.append({
                "filename": filename or "unnamed",
                "content_type": ctype,
                "size": len(payload),
                "content_id": strip_brackets(part.get("Content-ID")),
                "data": payload,
            })
            continue

        if ctype == "text/plain":
            try:
                text_parts.append(decode_text_part(part))
            except Exception:
                try:
                    text_parts.append(part.get_payload(decode=True).decode("utf-8", "replace"))
                except Exception:
                    pass
        elif ctype == "text/html":
            try:
                html_parts.append(decode_text_part(part))
            except Exception:
                try:
                    html_parts.append(part.get_payload(decode=True).decode("utf-8", "replace"))
                except Exception:
                    pass

    text = "\n\n".join(text_parts) if text_parts else None
    html = "\n\n".join(html_parts) if html_parts else None
    return text, html, atts


def save_attachments(message_id: int, atts: list[dict], conn):
    if not atts:
        return
    now = datetime.now(timezone.utc)
    att_dir = os.path.join(RAW_DIR, "attachments", now.strftime("%Y/%m/%d"), str(message_id))
    os.makedirs(att_dir, exist_ok=True)
    with conn.cursor() as cur:
        for a in atts:
            safe_name = re.sub(r"[^\w.\-]+", "_", a["filename"])[:200] or "unnamed"
            disk_path = os.path.join(att_dir, f"{uuid.uuid4().hex[:8]}_{safe_name}")
            with open(disk_path, "wb") as f:
                f.write(a["data"])
            cur.execute(
                "INSERT INTO attachments (message_id, filename, content_type, size_bytes, disk_path, content_id) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (message_id, a["filename"], a["content_type"], a["size"], disk_path, a["content_id"]),
            )


def ingest(raw: bytes, envelope_sender: str, envelope_recipient: str, source: str | None = None) -> int:
    raw_path = save_raw(raw)

    # Parse
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    message_id = strip_brackets(msg.get("Message-ID"))
    in_reply_to = strip_brackets(msg.get("In-Reply-To"))
    refs_raw = msg.get("References", "") or ""
    references = [strip_brackets(s) for s in refs_raw.split() if s]
    references = [r for r in references if r]

    subject = msg.get("Subject")
    from_name, from_email = parseaddr(msg.get("From", ""))
    from_email = (from_email or envelope_sender or "").lower()

    to_emails, _ = parse_addresses(msg.get("To"))
    cc_emails, _ = parse_addresses(msg.get("Cc"))
    reply_to_name, reply_to = parseaddr(msg.get("Reply-To", ""))

    # Date
    date_hdr = msg.get("Date")
    received_at = None
    if date_hdr:
        try:
            received_at = parsedate_to_datetime(date_hdr)
        except Exception:
            pass
    if received_at is None:
        received_at = datetime.now(timezone.utc)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)

    # Bodies + attachments
    body_text, body_html, atts = extract_bodies(msg)
    snippet = make_snippet(body_text, body_html)

    # Headers as JSON
    headers = {}
    for k, v in msg.items():
        headers.setdefault(k, []).append(str(v))

    with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
        thread_id = find_or_create_thread(
            conn, message_id, in_reply_to, references,
            subject, from_email, to_emails, received_at,
        )
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO messages
                   (thread_id, direction, message_id, in_reply_to, references_chain,
                    subject, from_email, from_name, to_emails, cc_emails, reply_to,
                    body_text, body_html, snippet, raw_path, size_bytes, has_attachments,
                    headers, received_at, parsed_at, parse_status)
                   VALUES (%s,'in',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),'parsed')
                   RETURNING id""",
                (
                    thread_id, message_id, in_reply_to, references,
                    subject, from_email, from_name, to_emails, cc_emails, reply_to or None,
                    body_text, body_html, snippet, raw_path, len(raw), bool(atts),
                    json.dumps(headers, default=str), received_at,
                ),
            )
            msg_id = cur.fetchone()[0]
            save_attachments(msg_id, atts, conn)

            # 把 envelope recipient 也并入 to_emails (实际投递目标)
            cur.execute(
                "UPDATE threads SET participants = array(SELECT DISTINCT unnest(participants || %s)) "
                "WHERE id = %s",
                ([envelope_recipient.lower()], thread_id),
            )
            if source:
                cur.execute("UPDATE threads SET source=%s WHERE id=%s", (source, thread_id))
        conn.commit()
    log(f"ingested msg_id={msg_id} thread={thread_id} from={from_email} to={envelope_recipient} subj={subject!r}")
    return 0


def main() -> int:
    # Postfix pipe argv: ${sender} ${original_recipient} ${recipient}
    sender = sys.argv[1] if len(sys.argv) > 1 else ""
    original_rcpt = sys.argv[2] if len(sys.argv) > 2 else ""
    recipient = sys.argv[3] if len(sys.argv) > 3 else original_rcpt

    raw = sys.stdin.buffer.read()
    if not raw:
        log("empty stdin, nothing to ingest", "WARN")
        return 0

    try:
        return ingest(raw, sender, recipient or original_rcpt)
    except Exception as e:
        log(f"ingest failed: {e!r}\n{traceback.format_exc()}", "ERROR")
        # Save raw even if parsing failed so we never lose mail
        try:
            raw_path = save_raw(raw)
            log(f"failed mail saved to {raw_path}", "WARN")
        except Exception:
            pass
        # Tempfail -> Postfix retries
        return 75


if __name__ == "__main__":
    sys.exit(main())
