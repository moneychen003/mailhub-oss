# Deploy Mailhub

The supported open-source deployment path is Docker Compose.

## One-command Bootstrap

```bash
bash scripts/bootstrap.sh http://localhost:3024
```

Pass your real public URL when deploying on a server:

```bash
bash scripts/bootstrap.sh https://mail.example.com
```

The script creates `.env` when missing, generates secrets, builds the containers, applies the database schema, and seeds the first admin account if `MAILHUB_ADMIN_PASSWORD` is set.

## Services

- `db` — Postgres 16
- `api` — FastAPI on port `8024`
- `web` — Next.js on port `3024`
- `classifier` — AI classification worker
- `imap-sync` — periodic IMAP pull worker

## After Deploy

1. Open `/setup` if no admin was seeded.
2. Open `/settings`.
3. Add a domain and copy the generated DNS records.
4. Configure SMTP and run the SMTP test.
5. Configure IMAP and run a one-time sync.
6. Configure AI and Telegram if needed.
7. Check Diagnostics before exposing the app publicly.
