# Mailhub

Mailhub is a self-hosted mail workflow app. It pulls or receives email, stores it in Postgres, classifies messages with an AI provider, and provides a web inbox with replies, scheduling, rules, templates, signatures, IMAP sync, SMTP sending, and optional Telegram alerts.

## Quick Start

```bash
git clone <your-mailhub-repo-url>
cd mailhub
bash scripts/bootstrap.sh http://localhost:3024
```

Open `http://localhost:3024`.

If the bootstrap script generated an admin password, it prints it and stores it in `.env`. If no admin password was configured, open `http://localhost:3024/setup` and create the first admin in the browser.

## Self-hosting Checklist

All routine setup lives in Settings:

- Installation status and writable path checks
- Public URL and inbound host
- Domains and DNS records
- SMTP or local Postfix outbound delivery
- IMAP inbound accounts
- AI provider configuration
- Telegram notification configuration
- Sender identities and signatures
- Classification rules and reply templates
- Users and diagnostics

See [SELF_HOSTING.md](SELF_HOSTING.md) for production deployment details.

## Development

Backend:

```bash
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://mailhub:password@127.0.0.1:5432/mailhub
uvicorn app.main:app --port 8024
```

Frontend:

```bash
cd web
pnpm install
pnpm dev
```

## Data Safety

Never commit `.env`, raw email, attachments, private keys, provider tokens, or real mailbox exports.
