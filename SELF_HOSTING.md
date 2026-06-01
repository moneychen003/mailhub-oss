# Self-hosting Mailhub

## 1. Deploy

Install Docker and run:

```bash
git clone <your-mailhub-repo-url>
cd mailhub
bash scripts/bootstrap.sh https://mail.example.com
```

For local testing:

```bash
bash scripts/bootstrap.sh http://localhost:3024
```

The script creates `.env`, generates `POSTGRES_PASSWORD` and `JWT_SECRET`, builds containers, applies `schema.sql`, creates runtime directories, and starts:

- Postgres
- FastAPI API
- Next.js web app
- AI classifier worker
- IMAP sync worker

## 2. First Login

If `.env` contains `MAILHUB_ADMIN_PASSWORD`, the runtime creates the admin user during first boot. The bootstrap script prints the generated password.

If you leave `MAILHUB_ADMIN_PASSWORD` empty, open:

```text
https://mail.example.com/setup
```

Create the first admin there. After that, manage users in Settings.

## 3. Site Settings

Open Settings -> Site and confirm:

- Public URL
- Inbound host
- Default timezone

These values drive generated DNS records and links in notifications.

## 4. Domains and DNS

Open Settings -> Domains, add your domain, then copy the generated records:

- MX: points mail delivery at your inbound host
- SPF: authorizes outbound senders
- DKIM: comes from your SMTP provider or OpenDKIM
- DMARC: publishes domain policy

Use Verify after DNS propagates. If you only use IMAP import from an existing mailbox, MX can stay with your current mail provider.

## 5. Outbound Mail

Open Settings -> Sending.

Recommended for most self-hosters: choose remote SMTP and enter:

- SMTP host
- Port
- Username
- App password
- STARTTLS or SSL/TLS

Run Test. Local Postfix is available as an advanced option when you operate your own mail server and DKIM signer.

## 6. Inbound Mail

Open Settings -> Receiving and add one or more IMAP accounts.

Use app-specific passwords for Gmail, QQ, 163, iCloud, Fastmail, or your mail provider. Click Test, then Sync Once. The `imap-sync` worker continues polling in the background.

Advanced direct MX delivery can pipe raw RFC822 mail into:

```bash
bin/ingest.py <sender> <original_recipient> <recipient>
```

## 7. AI and Telegram

Open Settings -> AI and configure an OpenAI-compatible or Anthropic-compatible endpoint. API keys are masked in the browser; leaving the key input empty keeps the current key.

Open Settings -> Telegram if you want priority alerts. Create a bot with BotFather, set `chat_id`, and run Test.

## 8. Senders, Signatures, Rules, Templates

Open Settings -> Senders to create sender identities under hosted domains. Each sender can have text and HTML signatures.

Rules can be created from a message or managed in Settings -> Rules. Templates are managed in Settings -> Templates.

## 9. Diagnostics

Open Settings -> Diagnostics before exposing the service publicly. Check:

- Database
- Runtime directories
- Local Postfix if used
- User/domain/sender counts
- IMAP account count
- AI queue count

## Common Commands

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f web
docker compose logs -f classifier
docker compose logs -f imap-sync
docker compose pull
docker compose up -d --build
```

## Backups

Back up the Postgres volume and the Mailhub data volume:

```bash
docker compose exec db pg_dump -U mailhub mailhub > mailhub.sql
docker run --rm -v mailhub_mailhub-data:/data -v "$PWD":/backup alpine tar czf /backup/mailhub-data.tgz /data
```

## Security

- Put Mailhub behind HTTPS.
- Keep `.env` private.
- Prefer provider app passwords over primary mailbox passwords.
- Use a strong admin password.
- Do not expose the API port publicly unless you know why.
