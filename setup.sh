#!/usr/bin/env bash
set -euo pipefail

echo "==> Preparing directories..."
mkdir -p data app

[ -f .env ] || cp .env.example .env

echo "==> Building DyerGate container..."
docker compose build

echo "==> Starting DyerGate..."
docker compose up -d

echo "==> Waiting for health..."
for i in {1..30}; do
  if curl -fsS http://localhost:8080/healthz > /dev/null 2>&1; then
    echo "STATUS: DyerGate online."
    exit 0
  fi
  sleep 1
done

echo "ERROR: DyerGate did not become healthy in time."
docker compose logs --tail=50
exit 1
