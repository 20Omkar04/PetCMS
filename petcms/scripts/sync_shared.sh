#!/usr/bin/env bash
# Copies the shared helper module into every service that needs it.
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGETS="auth-service user-service upload-service storage-service ai-tagging-service category-service search-service memory-service chatbot-service"
for svc in $TARGETS; do
  cp "$ROOT/_shared/common.py" "$ROOT/services/$svc/common.py"
done
echo "synced common.py into all services"
