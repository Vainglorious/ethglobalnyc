#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-"$ROOT_DIR/colony/.env"}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

SUPABASE_URL="${SUPABASE_URL:-${NEXT_PUBLIC_SUPABASE_URL:-}}"
SUPABASE_KEY="${SUPABASE_PUBLISHABLE_KEY:-${SUPABASE_ANON_KEY:-${NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY:-}}}"

if [[ -z "$SUPABASE_URL" || -z "$SUPABASE_KEY" ]]; then
  echo "Missing SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY in $ENV_FILE" >&2
  exit 2
fi

TMP_HEADERS="$(mktemp)"
TMP_BODY="$(mktemp)"
trap 'rm -f "$TMP_HEADERS" "$TMP_BODY"' EXIT

STATUS="$(
  curl -sS \
    -D "$TMP_HEADERS" \
    -o "$TMP_BODY" \
    -w "%{http_code}" \
    "${SUPABASE_URL%/}/rest/v1/colonies?select=pubkey,name,founded_at&limit=1" \
    -H "apikey: $SUPABASE_KEY" \
    -H "Authorization: Bearer $SUPABASE_KEY"
)"

echo "HTTP $STATUS"
cat "$TMP_BODY"
echo

if [[ "$STATUS" == "200" ]]; then
  echo "OK: public.colonies is reachable."
else
  echo "ERROR: public.colonies is not reachable yet." >&2
  echo "Apply frontend/supabase/schema.sql in the Supabase SQL editor, then rerun this check." >&2
  exit 1
fi
