"""Outbound: build RFC822 and submit through configured delivery transport."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, formataddr

from . import db


def build_message(
    from_email: str,
    from_name: str | None,
    to: list[str],
    cc: list[str],
    subject: str,
    body_text: str,
    body_html: str | None,
    in_reply_to: str | None,
    references: list[str] | None,
    bcc: list[str] | None = None,
) -> tuple[EmailMessage, str]:
    msg = EmailMessage()
    domain = from_email.split("@", 1)[1] if "@" in from_email else "localhost"
    msg_id = make_msgid(domain=domain)
    msg["Message-ID"] = msg_id
    # formataddr quotes the display name and rejects CR/LF injection — naive
    # string concat let a display_name like `"x"\r\nBcc: evil@…` slip through.
    msg["From"] = formataddr((from_name, from_email)) if from_name else from_email
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    # We deliberately do NOT add a Bcc header (leaks recipients). The submit()
    # path picks Bcc addresses up via _bcc_list below and passes them to
    # smtplib.send_message(to_addrs=...).
    if bcc:
        # Stash on the message object for submit() to read — never serialized.
        msg._bcc_list = list(bcc)  # type: ignore[attr-defined]
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    if in_reply_to:
        msg["In-Reply-To"] = f"<{in_reply_to}>"
    if references:
        msg["References"] = " ".join(f"<{r}>" for r in references)

    if body_html:
        msg.set_content(body_text or "")
        msg.add_alternative(body_html, subtype="html")
    else:
        msg.set_content(body_text or "")

    # Return both message and stripped message-id (no brackets)
    mid = msg_id.strip().lstrip("<").rstrip(">")
    return msg, mid


def _recipients(msg: EmailMessage) -> list[str]:
    rcpts: list[str] = []
    for h in ("To", "Cc"):
        v = msg.get(h, "")
        if v:
            rcpts.extend(a.strip() for a in v.split(",") if a.strip())
    # Bcc was stashed by build_message; never present as a header.
    rcpts.extend(getattr(msg, "_bcc_list", []) or [])
    return rcpts


def _send_with_client(client: smtplib.SMTP, msg: EmailMessage, rcpts: list[str]) -> None:
    client.ehlo()
    if rcpts:
        client.send_message(msg, to_addrs=rcpts)
    else:
        client.send_message(msg)


def _submit_local_postfix(msg: EmailMessage, rcpts: list[str]) -> None:
    with smtplib.SMTP("127.0.0.1", 25, timeout=30) as s:
        _send_with_client(s, msg, rcpts)


def _submit_smtp(msg: EmailMessage, rcpts: list[str], cfg: dict) -> None:
    host = cfg.get("host")
    port = int(cfg.get("port") or 587)
    if not host:
        raise RuntimeError("SMTP host is not configured")
    if cfg.get("use_tls"):
        client = smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context())
    else:
        client = smtplib.SMTP(host, port, timeout=30)
    with client as s:
        s.ehlo()
        if cfg.get("use_starttls") and not cfg.get("use_tls"):
            s.starttls(context=ssl.create_default_context())
            s.ehlo()
        if cfg.get("username"):
            s.login(cfg["username"], cfg.get("password") or "")
        if rcpts:
            s.send_message(msg, to_addrs=rcpts)
        else:
            s.send_message(msg)


def submit(msg: EmailMessage) -> None:
    """Submit via SMTP config; local Postfix remains the default transport."""
    rcpts = _recipients(msg)
    cfg = db.fetchone("SELECT * FROM smtp_config WHERE id=1")
    if cfg and cfg.get("enabled") and cfg.get("mode") == "smtp":
        _submit_smtp(msg, rcpts, cfg)
        return

    _submit_local_postfix(msg, rcpts)
