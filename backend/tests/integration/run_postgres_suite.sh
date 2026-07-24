#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)"
cd "$ROOT_DIR"

cleanup() {
  docker compose -f docker-compose.test.yml down >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker compose -f docker-compose.test.yml up -d --wait postgres
docker exec ai-interview-rls-test-postgres-1 \
  sh /docker-entrypoint-initdb.d/01-app-roles.sh

export TEST_DATABASE_URL="postgresql://app_runtime:runtime_test_password@127.0.0.1:55432/ai_interview_test"
export TEST_MIGRATION_DATABASE_URL="postgresql://app_migration:migration_test_password@127.0.0.1:55432/ai_interview_test"
export TEST_POSTGRES_ROLE_SCRIPT_VIA_COPY_PROGRAM=1
python -m pytest -q backend/tests/integration/test_postgres_rls.py
