#!/bin/sh
set -eu

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${APP_RUNTIME_PASSWORD:?APP_RUNTIME_PASSWORD is required}"
: "${APP_MIGRATION_PASSWORD:?APP_MIGRATION_PASSWORD is required}"

export PGUSER="$POSTGRES_USER"
export PGPASSWORD="$POSTGRES_PASSWORD"
export PGDATABASE="$POSTGRES_DB"

psql \
  --set=ON_ERROR_STOP=1 \
  --set=runtime_password="$APP_RUNTIME_PASSWORD" \
  --set=migration_password="$APP_MIGRATION_PASSWORD" \
  --set=database_name="$POSTGRES_DB" <<'SQL'
SELECT format(
  'CREATE ROLE app_migration LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
  :'migration_password'
)
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_migration')
\gexec

SELECT format(
  'ALTER ROLE app_migration PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
  :'migration_password'
)
\gexec

SELECT format(
  'CREATE ROLE app_runtime LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
  :'runtime_password'
)
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_runtime')
\gexec

SELECT format(
  'ALTER ROLE app_runtime PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
  :'runtime_password'
)
\gexec

-- NOINHERIT does not prevent SET ROLE. Remove every upstream membership for
-- the two application roles so neither can assume an owner or bypass role.
SELECT format('REVOKE %I FROM %I', parent.rolname, member.rolname)
FROM pg_auth_members membership
JOIN pg_roles parent ON parent.oid = membership.roleid
JOIN pg_roles member ON member.oid = membership.member
WHERE member.rolname IN ('app_runtime', 'app_migration')
\gexec

SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'database_name')
\gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM app_migration', :'database_name')
\gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM app_runtime', :'database_name')
\gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO app_migration', :'database_name')
\gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO app_runtime', :'database_name')
\gexec

REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO app_migration;
GRANT USAGE, CREATE ON SCHEMA public TO app_migration;
REVOKE ALL ON SCHEMA public FROM app_runtime;
GRANT USAGE ON SCHEMA public TO app_runtime;

SELECT format('ALTER TABLE %I.%I OWNER TO app_migration', schemaname, tablename)
FROM pg_tables
WHERE schemaname = 'public'
\gexec
SELECT format('ALTER SEQUENCE %I.%I OWNER TO app_migration', sequence_schema, sequence_name)
FROM information_schema.sequences
WHERE sequence_schema = 'public'
\gexec
SELECT CASE t.typtype
  WHEN 'e' THEN format('ALTER TYPE %I.%I OWNER TO app_migration', n.nspname, t.typname)
  WHEN 'd' THEN format('ALTER DOMAIN %I.%I OWNER TO app_migration', n.nspname, t.typname)
END
FROM pg_type t
JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = 'public'
  AND t.typtype IN ('e', 'd')
  AND t.typowner <> (SELECT oid FROM pg_roles WHERE rolname = 'app_migration')
\gexec

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM app_runtime;
SELECT format(
  'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I.%I TO app_runtime',
  schemaname,
  tablename
)
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename = ANY (ARRAY[
    'users', 'positions', 'position_events', 'question_banks', 'resumes', 'department_reviews',
    'interviews', 'interview_panels', 'offers', 'offer_templates',
    'offer_decision_audits',
    'coding_tests', 'coding_submissions', 'system_configs', 'workflows',
    'workflow_nodes', 'workflow_edges', 'workflow_executions',
    'workflow_node_executions', 'stored_files', 'tenants', 'tenant_domains',
    'platform_users', 'platform_audit_logs', 'public_access_tokens'
  ])
\gexec
SELECT format(
  'REVOKE UPDATE, DELETE ON TABLE %I.%I FROM app_runtime',
  schemaname,
  tablename
)
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename = ANY (ARRAY['position_events', 'offer_decision_audits'])
\gexec
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM app_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE app_migration IN SCHEMA public
  REVOKE ALL ON TABLES FROM app_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE app_migration IN SCHEMA public
  REVOKE ALL ON SEQUENCES FROM app_runtime;
SQL
