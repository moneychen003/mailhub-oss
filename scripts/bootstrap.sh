#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PUBLIC_URL="${1:-${API_BASE_URL:-http://localhost:3024}}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker, then rerun this script." >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose is required." >&2
  exit 1
fi

rand_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "${1:-24}"
  else
    od -An -N"${1:-24}" -tx1 /dev/urandom | tr -d ' \n'
    printf '\n'
  fi
}

set_env() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" .env; then
    local tmp
    tmp="$(mktemp)"
    awk -v k="$key" -v v="$value" 'BEGIN{done=0} $0 ~ "^" k "=" {$0=k "=" v; done=1} {print} END{if(!done) print k "=" v}' .env > "$tmp"
    mv "$tmp" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

if [ ! -f .env ]; then
  cp .env.example .env
  set_env POSTGRES_PASSWORD "$(rand_hex 18)"
  set_env JWT_SECRET "$(rand_hex 48)"
  set_env MAILHUB_ADMIN_PASSWORD "$(rand_hex 10)"
fi

set_env API_BASE_URL "$PUBLIC_URL"
if [[ "$PUBLIC_URL" == https://* ]]; then
  set_env COOKIE_SECURE "true"
else
  set_env COOKIE_SECURE "false"
fi

POSTGRES_PASSWORD="$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)"
POSTGRES_USER="$(grep '^POSTGRES_USER=' .env | cut -d= -f2-)"
POSTGRES_DB="$(grep '^POSTGRES_DB=' .env | cut -d= -f2-)"
set_env DATABASE_URL "postgresql://${POSTGRES_USER:-mailhub}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB:-mailhub}"

chmod 600 .env

"${COMPOSE[@]}" up -d --build

ADMIN_USER="$(grep '^MAILHUB_ADMIN_USERNAME=' .env | cut -d= -f2-)"
ADMIN_PASS="$(grep '^MAILHUB_ADMIN_PASSWORD=' .env | cut -d= -f2-)"

cat <<EOF

Mailhub is starting.

URL: ${PUBLIC_URL}
Setup page: ${PUBLIC_URL%/}/setup
Admin username: ${ADMIN_USER:-admin}
Admin password: ${ADMIN_PASS:-see .env or create one at /setup}

Next steps:
1. Open /settings after login.
2. Add a domain and copy the DNS records.
3. Configure SMTP and IMAP, then run the built-in tests.

EOF
