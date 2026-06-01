from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional
from .. import db, auth as authmod
from ..config_store import ensure_self_host_schema, get_app_config

router = APIRouter(prefix="/api/senders", tags=["senders"])


class SenderIn(BaseModel):
    email: EmailStr
    display_name: Optional[str] = None
    signature_text: Optional[str] = None
    signature_html: Optional[str] = None
    is_default: bool = False


class DomainIn(BaseModel):
    domain: str
    dkim_selector: str = "default"
    dkim_public_key: Optional[str] = None
    inbound_host: Optional[str] = None
    receive_enabled: bool = True
    send_enabled: bool = True
    notes: Optional[str] = None


def _normalize_domain(domain: str) -> str:
    value = domain.strip().lower()
    value = value.replace("https://", "").replace("http://", "").split("/", 1)[0].strip(".")
    if not value or "." not in value:
        raise HTTPException(400, "域名格式无效")
    return value


@router.get("")
def list_senders(user: dict = Depends(authmod.get_current_user)):
    ensure_self_host_schema()
    return db.fetchall(
        """SELECT s.id, s.email, s.display_name, s.signature_text, s.signature_html,
                  s.is_default, s.created_at,
                  d.domain, d.dkim_status
           FROM senders s LEFT JOIN domains d ON d.id=s.domain_id
           ORDER BY s.is_default DESC, s.email"""
    )


@router.post("")
def create_sender(body: SenderIn, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    # Sender records bind a hosted domain identity to outbound auth — only
    # admins may add or rotate them. Non-admins POSTing here previously could
    # mint a sender for any hosted domain.
    domain = body.email.split("@", 1)[1].lower()
    d = db.fetchone("SELECT id FROM domains WHERE domain=%s", (domain,))
    if not d:
        raise HTTPException(400, f"域名 {domain} 不在托管列表里")
    if body.is_default:
        db.execute("UPDATE senders SET is_default=false WHERE is_default=true")
    row = db.execute_returning(
        "INSERT INTO senders (email, display_name, domain_id, signature_text, signature_html, is_default, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (email) DO UPDATE SET display_name=EXCLUDED.display_name, "
        "signature_text=EXCLUDED.signature_text, signature_html=EXCLUDED.signature_html, "
        "is_default=EXCLUDED.is_default "
        "RETURNING id",
        (
            body.email.lower(),
            body.display_name,
            d["id"],
            body.signature_text,
            body.signature_html,
            body.is_default,
            user["id"],
        ),
    )
    return {"id": row["id"]}


@router.get("/domains")
def list_domains(user: dict = Depends(authmod.get_current_user)):
    ensure_self_host_schema()
    return db.fetchall(
        """SELECT id, domain, dkim_selector, dkim_public_key, inbound_host,
                  dkim_status, mx_status, spf_status, dmarc_status,
                  send_enabled, receive_enabled, notes, last_checked_at
           FROM domains ORDER BY domain"""
    )


@router.post("/domains")
def create_domain(body: DomainIn, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    domain = _normalize_domain(body.domain)
    app_cfg = get_app_config()
    inbound_host = body.inbound_host or app_cfg.get("inbound_host") or urlparse(app_cfg.get("public_base_url") or "").hostname
    row = db.execute_returning(
        """INSERT INTO domains
           (domain, dkim_selector, dkim_public_key, inbound_host, receive_enabled, send_enabled, notes)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (domain) DO UPDATE SET
             dkim_selector=EXCLUDED.dkim_selector,
             dkim_public_key=EXCLUDED.dkim_public_key,
             inbound_host=EXCLUDED.inbound_host,
             receive_enabled=EXCLUDED.receive_enabled,
             send_enabled=EXCLUDED.send_enabled,
             notes=EXCLUDED.notes
           RETURNING id""",
        (
            domain,
            body.dkim_selector.strip() or "default",
            body.dkim_public_key,
            inbound_host,
            body.receive_enabled,
            body.send_enabled,
            body.notes,
        ),
    )
    return {"id": row["id"]}


@router.put("/domains/{domain_id}")
def update_domain(domain_id: int, body: DomainIn, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    domain = _normalize_domain(body.domain)
    row = db.execute_returning(
        """UPDATE domains
           SET domain=%s, dkim_selector=%s, dkim_public_key=%s, inbound_host=%s,
               receive_enabled=%s, send_enabled=%s, notes=%s
           WHERE id=%s
           RETURNING id""",
        (
            domain,
            body.dkim_selector.strip() or "default",
            body.dkim_public_key,
            body.inbound_host,
            body.receive_enabled,
            body.send_enabled,
            body.notes,
            domain_id,
        ),
    )
    if not row:
        raise HTTPException(404, "域名不存在")
    return {"ok": True}


def _txt_values(name: str) -> list[str]:
    try:
        import dns.resolver
    except Exception:
        return []
    try:
        answers = dns.resolver.resolve(name, "TXT", lifetime=5)
        return ["".join(part.decode() if isinstance(part, bytes) else str(part) for part in r.strings) for r in answers]
    except Exception:
        return []


def _mx_values(name: str) -> list[str]:
    try:
        import dns.resolver
    except Exception:
        return []
    try:
        answers = dns.resolver.resolve(name, "MX", lifetime=5)
        return [str(r.exchange).rstrip(".").lower() for r in answers]
    except Exception:
        return []


@router.post("/domains/{domain_id}/verify")
def verify_domain(domain_id: int, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    d = db.fetchone("SELECT * FROM domains WHERE id=%s", (domain_id,))
    if not d:
        raise HTTPException(404, "域名不存在")
    domain = d["domain"]
    inbound = (d.get("inbound_host") or get_app_config().get("inbound_host") or "").rstrip(".").lower()
    mx_records = _mx_values(domain)
    spf_records = [v for v in _txt_values(domain) if v.lower().startswith("v=spf1")]
    dmarc_records = [v for v in _txt_values(f"_dmarc.{domain}") if v.lower().startswith("v=dmarc1")]
    dkim_records = _txt_values(f"{d.get('dkim_selector') or 'default'}._domainkey.{domain}")
    mx_ok = bool(mx_records) and (not inbound or inbound in mx_records)
    spf_ok = bool(spf_records)
    dmarc_ok = bool(dmarc_records)
    dkim_ok = bool(dkim_records) if d.get("dkim_public_key") else bool(dkim_records)
    db.execute(
        """UPDATE domains
           SET mx_status=%s, spf_status=%s, dmarc_status=%s, dkim_status=%s, last_checked_at=now()
           WHERE id=%s""",
        (
            "active" if mx_ok else "failed",
            "active" if spf_ok else "failed",
            "active" if dmarc_ok else "failed",
            "active" if dkim_ok else "failed",
            domain_id,
        ),
    )
    return {
        "ok": mx_ok and spf_ok and dmarc_ok and dkim_ok,
        "records": {
            "mx": mx_records,
            "spf": spf_records,
            "dmarc": dmarc_records,
            "dkim": dkim_records,
        },
    }


@router.get("/domains/{domain_id}/dns")
def domain_dns_records(domain_id: int, user: dict = Depends(authmod.get_current_user)):
    ensure_self_host_schema()
    d = db.fetchone("SELECT * FROM domains WHERE id=%s", (domain_id,))
    if not d:
        raise HTTPException(404, "域名不存在")
    domain = d["domain"]
    inbound = d.get("inbound_host") or get_app_config().get("inbound_host")
    selector = d.get("dkim_selector") or "default"
    dkim_value = f"v=DKIM1; k=rsa; p={d.get('dkim_public_key')}" if d.get("dkim_public_key") else "由你的 SMTP 服务商或 OpenDKIM 生成"
    return {
        "mx": {"name": "@", "type": "MX", "value": f"10 {inbound}"},
        "spf": {"name": "@", "type": "TXT", "value": "v=spf1 mx ~all"},
        "dkim": {"name": f"{selector}._domainkey", "type": "TXT", "value": dkim_value},
        "dmarc": {"name": "_dmarc", "type": "TXT", "value": f"v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}"},
    }


@router.delete("/domains/{domain_id}")
def delete_domain(domain_id: int, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    linked = db.fetchone("SELECT count(*)::int AS c FROM senders WHERE domain_id=%s", (domain_id,))
    if linked and linked["c"]:
        raise HTTPException(400, "这个域名仍有关联发件人，先删除发件人")
    db.execute("DELETE FROM domains WHERE id=%s", (domain_id,))
    return {"ok": True}


@router.delete("/{sender_id}")
def delete_sender(sender_id: int, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    db.execute("DELETE FROM senders WHERE id=%s", (sender_id,))
    return {"ok": True}
