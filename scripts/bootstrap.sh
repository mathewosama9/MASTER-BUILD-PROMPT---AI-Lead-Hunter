#!/usr/bin/env sh
# First-run helper: create .env with random secrets, start the stack, create the first admin.
#   ./scripts/bootstrap.sh admin@yourcompany.com "Your Agency"
set -eu
EMAIL="${1:?usage: bootstrap.sh EMAIL [WORKSPACE]}"
WORKSPACE="${2:-My Workspace}"
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  SECRET=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))")
  SVC=$(python3 -c "import secrets;print(secrets.token_urlsafe(32))")
  sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET|; s|^TELEGRAM_SERVICE_TOKEN=.*|TELEGRAM_SERVICE_TOKEN=$SVC|" .env && rm -f .env.bak
  echo "Created .env with random secrets"
fi

docker compose up -d --build
echo "Waiting for API..."
until docker compose exec -T api python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/v1/health')" >/dev/null 2>&1; do sleep 2; done
docker compose exec api python -m app.cli create-admin --email "$EMAIL" --workspace "$WORKSPACE"
echo "Done. Open http://localhost:3000 and sign in as $EMAIL"
