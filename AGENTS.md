# mailhub — AGENTS.md

Open-source mail management system: collect incoming mail into Postgres, classify with AI, expose a web inbox, support replies, scheduled sends, rules, templates, and optional Telegram alerts.

This file is for AI agents working in this repository. Frontend work under `web/` must also read `web/AGENTS.md`.

## Repository Structure

```
app/              FastAPI backend
  main.py         Application entry point and router registration
  routes/         Domain routes: auth, threads, search, config, senders,
                  folders, business, rules, drafts, templates, attachments,
                  contacts, exports, stats, scheduled, translate
  db.py           psycopg helpers
  auth.py         JWT cookie auth and admin/user ACL
  mail_send.py / outbound.py / send_queue.py
                  Outbound email and scheduled send queue
  tg.py           Telegram notifications
bin/
  bootstrap_runtime.py  Apply schema and seed first-run config
  ingest.py             Postfix pipe / raw RFC822 ingest
  imap_sync.py          IMAP pull sync
  ai_worker.py          AI classifier worker
web/              Next.js 15 + React 19 frontend
schema.sql        Postgres schema
docker-compose.yml
scripts/bootstrap.sh    One-command Docker Compose bootstrap
```

## Local Development

- Backend: set `DATABASE_URL`, then run `uvicorn app.main:app --port 8024`.
- Frontend: `cd web && pnpm install && pnpm dev` (port 3024).
- Frontend `/api/*` rewrites to `MAILHUB_API_INTERNAL_URL` or `http://127.0.0.1:8024`.
- Self-hosting: `bash scripts/bootstrap.sh http://localhost:3024`.

## Database Notes

- Fresh installs should apply `schema.sql`; running API also applies additive self-hosting migrations.
- Non-admin users only see threads where their email is a participant.
- Thread list order should remain `pinned DESC`, `pinned_at DESC NULLS LAST`, then `last_message_at DESC NULLS LAST`.

## Deployment Notes

- Public self-hosting target is Docker Compose.
- Keep `.env`, raw mail, attachments, logs, private keys, and provider tokens out of git.
- Do not commit user-specific domains, IP addresses, webhook URLs, credentials, or local filesystem paths.
- Generated deployment artifacts (`.next`, `node_modules`, `venv`, raw mail) are ignored.

## Known Implementation Details

- AI endpoints are configured in the UI and stored in `ai_config`; API keys should be masked when returned to browsers.
- Telegram is optional and configured in `tg_config`.
- Outbound delivery defaults to local Postfix but can be switched to SMTP in Settings.
- IMAP sources are optional and can be used instead of direct MX/Postfix ingest.
- `bin/ingest.py` is shared by Postfix and IMAP ingestion paths.
