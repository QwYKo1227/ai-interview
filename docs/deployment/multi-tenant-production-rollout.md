# 多租户生产发布、验收与回滚手册

本文用于把已有单租户生产实例升级为 Careray 与 Photonthix 共用的多租户实例。所有命令均在项目根目录执行；尖括号内容是必须由当班人员填写的占位符，不得把真实密码、令牌或私钥写入命令历史、工单或日志。

## 1. 发布原则与职责

本次升级同时修改数据库结构、历史文件位置、数据库访问角色和应用行为，必须在停止写入的维护窗口内完成。迁移校验器会短暂取消并恢复强制行级安全，因此运行校验器时后端必须停止。

发布前明确以下职责，并记录姓名、开始时间和沟通渠道：

- 发布负责人：执行 Compose、应用和 Caddy 操作，并作出继续或回滚决定。
- 数据库负责人：备份、恢复演练、Alembic、行级安全和数据校验。
- 文件负责人：备份并迁移 `backend_uploads`，核对历史文件。
- 业务验收人：分别使用 Careray、Photonthix 和平台管理员账号验收。
- 安全/网络负责人：内部 DNS、Caddy 根证书、HTTPS、SMTP 与密钥轮换。

发布前填好并双人复核：

```bash
set -euo pipefail
umask 077
read -r -p '生产环境变量文件绝对路径: ' ENV_FILE
test -r "$ENV_FILE" || { echo '环境变量文件不可读' >&2; exit 1; }
export RELEASE_ID='<YYYYMMDD-HHMM-commit>'
export RELEASE_DIR='/srv/ai-interview/releases/'"$RELEASE_ID"
export SERVER_IP='<internal-server-ip>'
export BACKUP_HOST='<off-host-backup-host>'
export BACKUP_DIR='<off-host-backup-directory>'
export EXPECTED_RTO_MINUTES='<RTO-minutes>'
export EXPECTED_RPO_MINUTES='<RPO-minutes>'
read -r -p 'PostgreSQL 管理用户名: ' POSTGRES_USER
read -r -p '生产数据库名: ' POSTGRES_DB
read -r -s -p 'app_runtime 数据库密码: ' APP_RUNTIME_PASSWORD; echo
read -r -s -p 'app_migration 数据库密码: ' APP_MIGRATION_PASSWORD; echo
export ENV_FILE POSTGRES_USER POSTGRES_DB APP_RUNTIME_PASSWORD APP_MIGRATION_PASSWORD
mkdir -p "$RELEASE_DIR"
```

检查 `.env`，不要输出其内容：

- `POSTGRES_PASSWORD`、`APP_RUNTIME_PASSWORD`、`APP_MIGRATION_PASSWORD` 使用不同强密码。
- `DATABASE_URL` 只能使用 `app_runtime`；`MIGRATION_DATABASE_URL` 只能使用 `app_migration`。
- `SECRET_KEY` 已安全生成，且与旧环境的令牌处理策略一致。
- `APP_ENV=production`。
- `APP_DOMAINS=interview.careray.com`，只对统一入口域名提供 HTTPS；dotenv 只能由 Compose 的 `--env-file` 解析，不能由 shell 执行。
- `UNIFIED_ENTRY_HOSTS=interview.careray.com`，明确声明承担“选择公司”功能的统一登录域名，禁止使用通配符。
- `TRUSTED_PROXY_CIDRS` 只包含生产 Caddy/Nginx 所在的受控容器网络 CIDR；不得填写 `0.0.0.0/0` 或 `::/0`。变更 Docker 网络后必须同步更新并重新验证客户端 IP。
- `CORS_ORIGINS=https://interview.careray.com`。
- LLM 和 SMTP 密钥通过受控密钥系统注入，未提交到仓库。
- 后端镜像使用已验收且不可变的版本或摘要；记录摘要到发布工单。

严禁用 `source`、点命令或 `eval` 执行 dotenv。下文每一条 Compose 命令都显式传入 `--env-file "$ENV_FILE"`；shell 需要的少量值只通过上面的交互读取。即使 dotenv 中包含空格或命令替换文本，它也只能作为 Compose 数据解析，不能作为 shell 程序执行。

## 2. 备份与恢复演练

### 2.1 数据库归档、校验和与异机保存

先确认生产仍在运行并记录备份开始时间。使用 PostgreSQL 自定义格式归档：

```bash
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
  > "$RELEASE_DIR/database-before.dump"
(cd "$RELEASE_DIR" && \
  sha256sum "$(basename "$RELEASE_DIR/database-before.dump")" \
  > "$(basename "$RELEASE_DIR/database-before.dump.sha256")")
scp "$RELEASE_DIR/database-before.dump" \
  "$RELEASE_DIR/database-before.dump.sha256" \
  "$BACKUP_HOST:$BACKUP_DIR/"
ssh "$BACKUP_HOST" "cd '$BACKUP_DIR' && sha256sum -c database-before.dump.sha256"
```

如果 Compose 未把上述 shell 变量传入容器，可把 `-U`、`-d` 后的值换成非敏感的数据库用户名和库名占位符；密码仍只能通过受控环境传递。

### 2.2 上传文件归档、校验和与异机保存

备份命名卷中的文件，不要使用 `docker compose down -v`：

```bash
docker run --rm \
  -v '<backend_uploads-volume-name>:/source:ro' \
  -v "$RELEASE_DIR:/backup" \
  alpine:3.20 sh -c 'cd /source && tar -czf /backup/uploads-before.tar.gz .'
(cd "$RELEASE_DIR" && \
  sha256sum "$(basename "$RELEASE_DIR/uploads-before.tar.gz")" \
  > "$(basename "$RELEASE_DIR/uploads-before.tar.gz.sha256")")
scp "$RELEASE_DIR/uploads-before.tar.gz" \
  "$RELEASE_DIR/uploads-before.tar.gz.sha256" \
  "$BACKUP_HOST:$BACKUP_DIR/"
ssh "$BACKUP_HOST" "cd '$BACKUP_DIR' && sha256sum -c uploads-before.tar.gz.sha256"
```

卷名可能带有不同的 Compose 项目前缀，先用 `docker volume ls` 确认实际的 `backend_uploads` 卷名，再替换命令中的占位值。

### 2.3 在克隆环境恢复演练

禁止把演练恢复到生产库或生产卷。下面使用独立网络、容器和卷恢复停写前副本，并在副本上走完角色初始化、迁移、回填、验证和双租户 RLS 冒烟；任一命令失败都会因 `set -euo pipefail` 退出。后端镜像必须填写已构建的不可变摘要。

```bash
export DRILL_ID="ai-interview-drill-$RELEASE_ID"
export DRILL_NETWORK="$DRILL_ID-network"
export DRILL_DB_CONTAINER="$DRILL_ID-postgres"
export DRILL_BACKEND_CONTAINER="$DRILL_ID-backend"
export DRILL_DB_VOLUME="$DRILL_ID-postgres-data"
export DRILL_UPLOAD_VOLUME="$DRILL_ID-uploads"
export DRILL_DB='ai_interview_drill'
export DRILL_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export DRILL_RUNTIME_PASSWORD="$(openssl rand -hex 24)"
export DRILL_MIGRATION_PASSWORD="$(openssl rand -hex 24)"
export BACKEND_IMAGE='<validated-backend-image@sha256:digest>'
export DRILL_MIGRATION_URL="postgresql://app_migration:${DRILL_MIGRATION_PASSWORD}@${DRILL_DB_CONTAINER}:5432/${DRILL_DB}"
export DRILL_RUNTIME_URL="postgresql://app_runtime:${DRILL_RUNTIME_PASSWORD}@${DRILL_DB_CONTAINER}:5432/${DRILL_DB}"

# BEGIN DRILL CLEANUP TRAP
cleanup_drill() {
  local cleanup_status="${1:-$?}"
  local containers=()
  trap - EXIT INT TERM HUP
  [[ -n "${DRILL_BACKEND_CONTAINER:-}" ]] && containers+=("$DRILL_BACKEND_CONTAINER")
  [[ -n "${DRILL_DB_CONTAINER:-}" ]] && containers+=("$DRILL_DB_CONTAINER")
  if ((${#containers[@]})); then
    docker rm -f "${containers[@]}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${DRILL_NETWORK:-}" ]]; then
    docker network rm "$DRILL_NETWORK" >/dev/null 2>&1 || true
  fi
  unset DRILL_POSTGRES_PASSWORD DRILL_RUNTIME_PASSWORD DRILL_MIGRATION_PASSWORD
  unset DRILL_MIGRATION_URL DRILL_RUNTIME_URL DRILL_SECRET_KEY
  unset DRILL_PLATFORM_PASSWORD DRILL_CARERAY_PASSWORD DRILL_PHOTON_PASSWORD
  unset DRILL_PLATFORM_TOKEN DRILL_CAR_TOKEN DRILL_PHOTON_TOKEN
  return "$cleanup_status"
}
trap 'cleanup_status=$?; cleanup_drill "$cleanup_status"; exit "$cleanup_status"' EXIT
trap 'cleanup_drill 130; exit 130' INT
trap 'cleanup_drill 143; exit 143' TERM
trap 'cleanup_drill 129; exit 129' HUP
# END DRILL CLEANUP TRAP

docker network create "$DRILL_NETWORK"
docker volume create "$DRILL_DB_VOLUME"
docker volume create "$DRILL_UPLOAD_VOLUME"
docker run -d --name "$DRILL_DB_CONTAINER" --network "$DRILL_NETWORK" \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD="$DRILL_POSTGRES_PASSWORD" \
  -e POSTGRES_DB="$DRILL_DB" \
  -e APP_RUNTIME_PASSWORD="$DRILL_RUNTIME_PASSWORD" \
  -e APP_MIGRATION_PASSWORD="$DRILL_MIGRATION_PASSWORD" \
  -v "$DRILL_DB_VOLUME:/var/lib/postgresql/data" \
  -v "$PWD/docker/postgres/init/01-app-roles.sh:/docker-entrypoint-initdb.d/01-app-roles.sh:ro" \
  postgres:15-alpine
until docker exec -e PGPASSWORD="$DRILL_POSTGRES_PASSWORD" "$DRILL_DB_CONTAINER" \
  pg_isready -U postgres -d "$DRILL_DB"; do sleep 2; done

if ! docker exec -i -e PGPASSWORD="$DRILL_POSTGRES_PASSWORD" \
  "$DRILL_DB_CONTAINER" pg_restore -U postgres -d "$DRILL_DB" \
  --clean --if-exists --no-owner < "$RELEASE_DIR/database-before.dump"; then
  echo '副本数据库恢复失败' >&2
  exit 1
fi
if ! docker exec "$DRILL_DB_CONTAINER" \
  sh /docker-entrypoint-initdb.d/01-app-roles.sh; then
  echo '副本角色初始化失败' >&2
  exit 1
fi
if ! docker run --rm \
  -v "$DRILL_UPLOAD_VOLUME:/restore" \
  -v "$RELEASE_DIR:/backup:ro" \
  alpine:3.20 sh -c 'cd /restore && tar -xzf /backup/uploads-before.tar.gz'; then
  echo '副本上传文件恢复失败' >&2
  exit 1
fi
```

先用权威目录保存副本迁移前 18 表 JSON/CSV；缺失的新表会稳定记录为 `present=false, rows=0`：

```bash
if ! docker run --rm --network "$DRILL_NETWORK" \
  -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
  -v "$DRILL_UPLOAD_VOLUME:/app/uploads" \
  -v "$RELEASE_DIR:/artifacts" \
  "$BACKEND_IMAGE" python scripts/snapshot_tenant_counts.py snapshot \
  --json /artifacts/drill-counts-before.json \
  --csv /artifacts/drill-counts-before.csv; then
  echo '副本迁移前18表快照失败' >&2
  exit 1
fi
if ! docker run --rm --network "$DRILL_NETWORK" \
  -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
  -v "$DRILL_UPLOAD_VOLUME:/app/uploads" \
  "$BACKEND_IMAGE" alembic upgrade m2n3o4p5q6r7; then
  echo '副本兼容迁移失败' >&2
  exit 1
fi
if ! docker run --rm --network "$DRILL_NETWORK" \
  -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
  -e LEGACY_UPLOAD_ROOT=/app/uploads -e UPLOAD_ROOT=/app/uploads \
  -v "$DRILL_UPLOAD_VOLUME:/app/uploads" \
  "$BACKEND_IMAGE" python scripts/backfill_legacy_uploads.py inventory --dry-run \
  | tee "$RELEASE_DIR/drill-backfill-inventory.json"; then
  echo '副本历史文件盘点失败' >&2
  exit 1
fi
if ! docker run --rm --network "$DRILL_NETWORK" \
  -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
  -e LEGACY_UPLOAD_ROOT=/app/uploads -e UPLOAD_ROOT=/app/uploads \
  -v "$DRILL_UPLOAD_VOLUME:/app/uploads" \
  "$BACKEND_IMAGE" python scripts/backfill_legacy_uploads.py migrate --dry-run \
  | tee "$RELEASE_DIR/drill-backfill-dry-run.json"; then
  echo '副本历史文件演练失败' >&2
  exit 1
fi
if ! docker run --rm -v "$RELEASE_DIR:/artifacts:ro" \
  "$BACKEND_IMAGE" python scripts/legacy_backfill_gate.py plan \
  --inventory /artifacts/drill-backfill-inventory.json \
  --dry-run /artifacts/drill-backfill-dry-run.json \
  | tee "$RELEASE_DIR/drill-backfill-plan.json"; then
  echo '副本历史文件计划不一致' >&2
  exit 1
fi
DRILL_BACKFILL_ACTION="$(jq -er '.action' "$RELEASE_DIR/drill-backfill-plan.json")"
DRILL_BACKFILL_PENDING="$(jq -er '.pending' "$RELEASE_DIR/drill-backfill-plan.json")"
if [[ "$DRILL_BACKFILL_ACTION" == "migrate" ]]; then
  if docker run --rm --network "$DRILL_NETWORK" \
    -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
    -e LEGACY_UPLOAD_ROOT=/app/uploads -e UPLOAD_ROOT=/app/uploads \
    -v "$DRILL_UPLOAD_VOLUME:/app/uploads" \
    "$BACKEND_IMAGE" python scripts/backfill_legacy_uploads.py verify \
    | tee "$RELEASE_DIR/drill-backfill-verify-before.json"; then
    echo '副本存在pending时verify意外成功' >&2
    exit 1
  fi
  if ! jq -e --argjson expected "$DRILL_BACKFILL_PENDING" \
    '.schema == "ai-interview.legacy-upload-backfill" and .ok == false and .counts.pending == $expected and .counts.errors == 0' \
    "$RELEASE_DIR/drill-backfill-verify-before.json" >/dev/null; then
    echo '副本迁移前verify不是预期pending失败' >&2
    exit 1
  fi
  if ! docker run --rm --network "$DRILL_NETWORK" \
    -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
    -e LEGACY_UPLOAD_ROOT=/app/uploads -e UPLOAD_ROOT=/app/uploads \
    -v "$DRILL_UPLOAD_VOLUME:/app/uploads" \
    "$BACKEND_IMAGE" python scripts/backfill_legacy_uploads.py migrate \
    | tee "$RELEASE_DIR/drill-backfill.json"; then
    echo '副本历史文件回填失败' >&2
    exit 1
  fi
  if ! docker run --rm -v "$RELEASE_DIR:/artifacts:ro" \
    "$BACKEND_IMAGE" python scripts/legacy_backfill_gate.py finalize \
    --plan /artifacts/drill-backfill-plan.json \
    --migration /artifacts/drill-backfill.json \
    | tee "$RELEASE_DIR/drill-backfill-result.json"; then
    echo '副本实际迁移数与pending不一致' >&2
    exit 1
  fi
else
  if ! docker run --rm --network "$DRILL_NETWORK" \
    -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
    -e LEGACY_UPLOAD_ROOT=/app/uploads -e UPLOAD_ROOT=/app/uploads \
    -v "$DRILL_UPLOAD_VOLUME:/app/uploads" \
    "$BACKEND_IMAGE" python scripts/backfill_legacy_uploads.py verify \
    | tee "$RELEASE_DIR/drill-backfill-verify-before.json"; then
    echo '副本零pending时verify失败' >&2
    exit 1
  fi
  if ! jq -e \
    '.schema == "ai-interview.legacy-upload-backfill" and .ok == true and .counts.pending == 0 and .counts.errors == 0' \
    "$RELEASE_DIR/drill-backfill-verify-before.json" >/dev/null; then
    echo '副本零pending校验JSON异常' >&2
    exit 1
  fi
  if ! docker run --rm -v "$RELEASE_DIR:/artifacts:ro" \
    "$BACKEND_IMAGE" python scripts/legacy_backfill_gate.py finalize \
    --plan /artifacts/drill-backfill-plan.json \
    | tee "$RELEASE_DIR/drill-backfill-result.json"; then
    echo '副本零pending收尾失败' >&2
    exit 1
  fi
fi
DRILL_STORED_FILE_INCREASE="$(jq -er \
  '.stored_files_increase' "$RELEASE_DIR/drill-backfill-result.json")"
if ! docker run --rm --network "$DRILL_NETWORK" \
  -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
  -e LEGACY_UPLOAD_ROOT=/app/uploads -e UPLOAD_ROOT=/app/uploads \
  -v "$DRILL_UPLOAD_VOLUME:/app/uploads" \
  "$BACKEND_IMAGE" python scripts/backfill_legacy_uploads.py verify \
  | tee "$RELEASE_DIR/drill-backfill-verify.json"; then
  echo '副本仍有旧文件或恶意路径' >&2
  exit 1
fi
if ! jq -e \
  '.schema == "ai-interview.legacy-upload-backfill" and .ok == true and .counts.pending == 0 and .counts.errors == 0' \
  "$RELEASE_DIR/drill-backfill-verify.json" >/dev/null; then
  echo '副本最终历史文件JSON门禁失败' >&2
  exit 1
fi
if ! docker run --rm --network "$DRILL_NETWORK" \
  -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
  -v "$DRILL_UPLOAD_VOLUME:/app/uploads" \
  "$BACKEND_IMAGE" alembic upgrade head; then
  echo '副本head迁移失败' >&2
  exit 1
fi
if ! docker exec "$DRILL_DB_CONTAINER" \
  sh /docker-entrypoint-initdb.d/01-app-roles.sh; then
  echo '副本head后权限收敛失败' >&2
  exit 1
fi
if ! docker run --rm --network "$DRILL_NETWORK" \
  -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
  "$BACKEND_IMAGE" python scripts/verify_database_permissions.py \
  | tee "$RELEASE_DIR/drill-database-permissions.json"; then
  echo '副本数据库权限门禁失败' >&2
  exit 1
fi
```

权限 JSON 必须同时满足 `session_identity_valid=true`、`application_role_memberships=0`，并显示 23 张应用表拥有精确 DML。验证器要求 `session_user` 与 `current_user` 都是 `app_migration`，因此管理账号通过 `SET ROLE` 冒充也会失败；任一应用数据库角色残留上游 membership 同样阻断演练。

升级后再次保存同一 18 表，并把回填 JSON 中实际 `migrated` 数作为唯一允许的 `stored_files` 增量；其余 17 表必须严格相等，`stored_files` 也必须精确相差该数，默认允许增量为零：

```bash
if ! docker run --rm --network "$DRILL_NETWORK" \
  -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
  -v "$DRILL_UPLOAD_VOLUME:/app/uploads" \
  -v "$RELEASE_DIR:/artifacts" \
  "$BACKEND_IMAGE" python scripts/snapshot_tenant_counts.py snapshot \
  --json /artifacts/drill-counts-after.json \
  --csv /artifacts/drill-counts-after.csv; then
  echo '副本迁移后18表快照失败' >&2
  exit 1
fi
if ! docker run --rm \
  -v "$RELEASE_DIR:/artifacts:ro" \
  "$BACKEND_IMAGE" python scripts/snapshot_tenant_counts.py compare \
  --before /artifacts/drill-counts-before.json \
  --after /artifacts/drill-counts-after.json \
  --allow-stored-files-increase "$DRILL_STORED_FILE_INCREASE" \
  | tee "$RELEASE_DIR/drill-count-comparison.json"; then
  echo '副本18表逐表机器比较失败' >&2
  exit 1
fi
if ! docker run --rm --network "$DRILL_NETWORK" \
  -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
  -v "$DRILL_UPLOAD_VOLUME:/app/uploads" \
  "$BACKEND_IMAGE" python scripts/verify_tenant_migration.py \
  | tee "$RELEASE_DIR/drill-tenant-verification.json"; then
  echo '副本租户迁移验证失败' >&2
  exit 1
fi
```

检查 Alembic head、18 个 FORCE RLS、29 个复合外键和全部原生枚举标签；随后创建 Photonthix 的副本数据，用 `app_runtime` 分别设置两个租户上下文，确认各自只看到一条 smoke 职位且交叉为零：

```bash
if ! docker run --rm --network "$DRILL_NETWORK" \
  -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
  "$BACKEND_IMAGE" alembic current | tee "$RELEASE_DIR/drill-alembic-current.txt"; then
  echo '副本Alembic head检查失败' >&2
  exit 1
fi
grep -q 'r7s8t9u0v1w2' "$RELEASE_DIR/drill-alembic-current.txt" \
  || { echo '副本不在Alembic head' >&2; exit 1; }
if ! docker exec -e PGPASSWORD="$DRILL_MIGRATION_PASSWORD" \
  "$DRILL_DB_CONTAINER" psql -U app_migration -d "$DRILL_DB" \
  -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace AND relname = ANY(ARRAY['users','positions','question_banks','resumes','department_reviews','interviews','interview_panels','offers','offer_templates','coding_tests','coding_submissions','system_configs','workflows','workflow_nodes','workflow_edges','workflow_executions','workflow_node_executions','stored_files']) AND relrowsecurity AND relforcerowsecurity" \
  | grep -qx '18'; then
  echo '副本FORCE RLS数量不是18' >&2
  exit 1
fi
if ! docker exec -e PGPASSWORD="$DRILL_MIGRATION_PASSWORD" \
  "$DRILL_DB_CONTAINER" psql -U app_migration -d "$DRILL_DB" \
  -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM pg_constraint WHERE contype='f' AND conname LIKE 'fk_%_tenant' AND array_length(conkey,1)=2" \
  | grep -qx '29'; then
  echo '副本复合外键数量不是29' >&2
  exit 1
fi
if ! docker run --rm -i --network "$DRILL_NETWORK" \
  -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
  "$BACKEND_IMAGE" python - <<'PY'
from sqlalchemy import create_engine, text
from app.models.base import Base
import os
expected = {}
for table in Base.metadata.sorted_tables:
    for column in table.columns:
        labels = getattr(column.type, "enums", None)
        if labels and getattr(column.type, "native_enum", False):
            expected.setdefault(column.type.name, set()).update(labels)
engine = create_engine(os.environ["MIGRATION_DATABASE_URL"])
with engine.connect() as connection:
    rows = connection.execute(text("SELECT t.typname,e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid=t.oid JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public'"))
    actual = {}
    for name, label in rows:
        actual.setdefault(name, set()).add(label)
assert actual == expected, "native enum labels do not match runtime metadata"
PY
then
  echo '副本枚举标签检查失败' >&2
  exit 1
fi
```

最后在隔离副本上真正启动同一镜像，只绑定回环地址，不接入生产 Caddy。通过平台 API 入驻一个唯一的 Photonthix 演练租户；再为恢复出的 Careray 创建同邮箱、不同密码管理员，用真实登录与职位 API 验证双租户隔离：

```bash
export DRILL_API_PORT=18080
export DRILL_SECRET_KEY="$(openssl rand -hex 32)"
export DRILL_PLATFORM_EMAIL="platform-$RELEASE_ID@example.invalid"
export DRILL_PLATFORM_PASSWORD="A$(openssl rand -hex 18)9"
export DRILL_SHARED_EMAIL="isolation-$RELEASE_ID@example.invalid"
export DRILL_CARERAY_PASSWORD="C$(openssl rand -hex 18)7"
export DRILL_PHOTON_PASSWORD="P$(openssl rand -hex 18)8"
export DRILL_PHOTON_CODE="photonthix-drill-$(date +%s)"
export DRILL_PHOTON_DOMAIN="$DRILL_PHOTON_CODE.example.invalid"
export DRILL_CAR_TITLE="careray-smoke-$RELEASE_ID"
export DRILL_PHOTON_TITLE="photonthix-smoke-$RELEASE_ID"

if ! docker run --rm --network "$DRILL_NETWORK" \
  -e DATABASE_URL="$DRILL_RUNTIME_URL" \
  -e MIGRATION_DATABASE_URL="$DRILL_MIGRATION_URL" \
  -e PLATFORM_ADMIN_EMAIL="$DRILL_PLATFORM_EMAIL" \
  -e PLATFORM_ADMIN_PASSWORD="$DRILL_PLATFORM_PASSWORD" \
  "$BACKEND_IMAGE" python scripts/create_platform_admin.py; then
  echo '副本平台管理员创建失败' >&2
  exit 1
fi
if ! docker run -d --name "$DRILL_BACKEND_CONTAINER" \
  --network "$DRILL_NETWORK" -p "127.0.0.1:${DRILL_API_PORT}:8000" \
  -e DATABASE_URL="$DRILL_RUNTIME_URL" -e APP_ENV=production \
  -e UNIFIED_ENTRY_HOSTS=127.0.0.1 \
  -e SECRET_KEY="$DRILL_SECRET_KEY" \
  -e APP_DOMAINS="careray.example.invalid, $DRILL_PHOTON_DOMAIN" \
  -e UPLOAD_ROOT=/app/uploads \
  -v "$DRILL_UPLOAD_VOLUME:/app/uploads" \
  "$BACKEND_IMAGE" uvicorn app.main:app --host 0.0.0.0 --port 8000; then
  echo '副本后端启动失败' >&2
  exit 1
fi
until curl --fail --silent "http://127.0.0.1:${DRILL_API_PORT}/" >/dev/null; do
  sleep 2
done
DRILL_PLATFORM_TOKEN="$(curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg email "$DRILL_PLATFORM_EMAIL" \
    --arg password "$DRILL_PLATFORM_PASSWORD" \
    '{email:$email,password:$password}')" \
  "http://127.0.0.1:${DRILL_API_PORT}/api/platform/auth/login" \
  | jq -er '.access_token')"
if ! curl --fail --silent --show-error \
  -H "Authorization: Bearer $DRILL_PLATFORM_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg code "$DRILL_PHOTON_CODE" \
    --arg email "$DRILL_SHARED_EMAIL" \
    --arg password "$DRILL_PHOTON_PASSWORD" \
    '{code:$code,name:"Photonthix Drill",admin_email:$email,admin_password:$password}')" \
  "http://127.0.0.1:${DRILL_API_PORT}/api/platform/tenants" \
  | tee "$RELEASE_DIR/drill-photonthix-onboarding.json" >/dev/null; then
  echo '副本Photonthix入驻失败' >&2
  exit 1
fi
if ! docker run --rm -i --network "$DRILL_NETWORK" \
  -e DATABASE_URL="$DRILL_RUNTIME_URL" \
  -e DRILL_SHARED_EMAIL -e DRILL_CARERAY_PASSWORD \
  "$BACKEND_IMAGE" python - <<'PY'
import os
from app.config.database import SessionLocal
from app.config.tenant_session import tenant_session
from app.core.security import get_password_hash
from app.models.models import User, UserRole
from app.models.tenant_models import Tenant
control = SessionLocal()
try:
    tenant = control.query(Tenant).filter(Tenant.code == "careray").one()
    tenant_id = tenant.id
finally:
    control.close()
with tenant_session(tenant_id) as db:
    assert db.query(User).filter(User.email == os.environ["DRILL_SHARED_EMAIL"]).first() is None
    db.add(User(email=os.environ["DRILL_SHARED_EMAIL"],
                hashed_password=get_password_hash(os.environ["DRILL_CARERAY_PASSWORD"]),
                full_name="Careray Drill", role=UserRole.ADMIN))
    db.commit()
PY
then
  echo '副本Careray同邮箱用户创建失败' >&2
  exit 1
fi

DRILL_CAR_TOKEN="$(curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg email "$DRILL_SHARED_EMAIL" \
    --arg password "$DRILL_CARERAY_PASSWORD" \
    '{tenant_code:"careray",email:$email,password:$password}')" \
  "http://127.0.0.1:${DRILL_API_PORT}/api/auth/login" | jq -er '.access_token')"
DRILL_PHOTON_TOKEN="$(curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg code "$DRILL_PHOTON_CODE" --arg email "$DRILL_SHARED_EMAIL" \
    --arg password "$DRILL_PHOTON_PASSWORD" \
    '{tenant_code:$code,email:$email,password:$password}')" \
  "http://127.0.0.1:${DRILL_API_PORT}/api/auth/login" | jq -er '.access_token')"
if curl --fail --silent -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg email "$DRILL_SHARED_EMAIL" --arg password "$DRILL_PHOTON_PASSWORD" \
    '{tenant_code:"careray",email:$email,password:$password}')" \
  "http://127.0.0.1:${DRILL_API_PORT}/api/auth/login" >/dev/null; then
  echo '副本错误公司/密码组合意外登录成功' >&2
  exit 1
fi
if ! curl --fail --silent --show-error \
  -H "Authorization: Bearer $DRILL_CAR_TOKEN" -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg title "$DRILL_CAR_TITLE" \
    '{title:$title,description:"tenant isolation smoke"}')" \
  "http://127.0.0.1:${DRILL_API_PORT}/api/positions" >/dev/null; then
  echo '副本Careray职位创建失败' >&2
  exit 1
fi
if ! curl --fail --silent --show-error \
  -H "Authorization: Bearer $DRILL_PHOTON_TOKEN" -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg title "$DRILL_PHOTON_TITLE" \
    '{title:$title,description:"tenant isolation smoke"}')" \
  "http://127.0.0.1:${DRILL_API_PORT}/api/positions" >/dev/null; then
  echo '副本Photonthix职位创建失败' >&2
  exit 1
fi
if ! curl --fail --silent --show-error \
  -H "Authorization: Bearer $DRILL_CAR_TOKEN" \
  "http://127.0.0.1:${DRILL_API_PORT}/api/positions" \
  | jq -e --arg own "$DRILL_CAR_TITLE" --arg other "$DRILL_PHOTON_TITLE" \
    '([.[]|select(.title==$own)]|length)==1 and ([.[]|select(.title==$other)]|length)==0' >/dev/null; then
  echo '副本Careray列表隔离失败' >&2
  exit 1
fi
if ! curl --fail --silent --show-error \
  -H "Authorization: Bearer $DRILL_PHOTON_TOKEN" \
  "http://127.0.0.1:${DRILL_API_PORT}/api/positions" \
  | jq -e --arg own "$DRILL_PHOTON_TITLE" --arg other "$DRILL_CAR_TITLE" \
    '([.[]|select(.title==$own)]|length)==1 and ([.[]|select(.title==$other)]|length)==0' >/dev/null; then
  echo '副本Photonthix列表隔离失败' >&2
  exit 1
fi
```

数据库、文件、18 表对比、枚举、同邮箱登录和职位隔离全部通过后，记录恢复开始、数据库可用、文件可用和 smoke 完成时间；实测恢复耗时必须小于 RTO。RPO 是最后一致性副本与故障时刻之间可能丢失的数据时间。演练容器可删除，但副本卷和全部证据保留到生产观察期结束：

```bash
cleanup_drill 0
```

## 3. 发布前快照和停止写入

记录当前版本和容器，输出只保存到受控发布目录：

```bash
git rev-parse HEAD | tee "$RELEASE_DIR/source-commit.txt"
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml images \
  | tee "$RELEASE_DIR/images-before.txt"
```

宣布维护窗口，禁止新登录和写入，然后停止会写数据库的应用容器：

```bash
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml stop backend frontend caddy
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml ps
```

确认没有应用连接和未完成事务后，再做一份“停止写入后”的最终数据库与文件备份，重复第 2 节的校验和及异机上传步骤。随后幂等初始化角色，并用与副本演练相同的权威脚本保存正式迁移前 18 表 JSON/CSV：

```bash
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm postgres-init; then
  echo '生产角色初始化失败' >&2
  exit 1
fi
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm \
  -v "$RELEASE_DIR:/artifacts" backend-migrate \
  python scripts/snapshot_tenant_counts.py snapshot \
  --json /artifacts/production-counts-before.json \
  --csv /artifacts/production-counts-before.csv; then
  echo '生产迁移前18表快照失败' >&2
  exit 1
fi
```

后续所有阶段出现不可解释差异时立即停止，不要尝试带病继续。

## 4. 分阶段兼容升级

### 4.1 启动数据库角色并检查迁移链

```bash
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml up -d postgres; then
  echo '生产PostgreSQL启动失败' >&2
  exit 1
fi
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm postgres-init; then
  echo '生产角色初始化失败' >&2
  exit 1
fi
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm backend-migrate \
  alembic current | tee "$RELEASE_DIR/production-alembic-current-before.txt"; then
  echo '读取生产当前Alembic版本失败' >&2
  exit 1
fi
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm backend-migrate \
  alembic heads | tee "$RELEASE_DIR/production-alembic-heads.txt"; then
  echo '读取生产Alembic head失败' >&2
  exit 1
fi
```

`postgres-init` 必须成功建立受限的 `app_runtime` 和 DDL 专用的 `app_migration`。任何时候都不得让后端使用 PostgreSQL 管理账号。

### 4.2 只升级到租户文件兼容阶段

先执行租户基础和存储文件迁移，但暂不启用强制 RLS：

```bash
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm backend-migrate \
  alembic upgrade m2n3o4p5q6r7; then
  echo '生产兼容迁移失败' >&2
  exit 1
fi
```

检查 Careray 已成为既有数据的默认租户，所有租户表 `tenant_id` 均无空值，复合外键没有跨租户引用。同一租户内的用户邮箱必须大小写不敏感唯一；不同租户允许同邮箱。

### 4.3 盘点、演练并迁移历史上传

历史字段包括简历 `file_path/file_id`、题库 `source_file/source_file_id` 和面试音频 JSON。迁移工具只复制并原子落盘，不删除旧文件。缺失、软链接、目录穿越或不属于当前租户的路径会被拒绝。

```bash
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm backend-migrate \
  python scripts/backfill_legacy_uploads.py inventory --dry-run \
  | tee "$RELEASE_DIR/uploads-inventory.json"; then
  echo '生产历史文件盘点失败' >&2
  exit 1
fi
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm backend-migrate \
  python scripts/backfill_legacy_uploads.py migrate --dry-run \
  | tee "$RELEASE_DIR/uploads-migrate-dry-run.json"; then
  echo '生产历史文件迁移演练失败' >&2
  exit 1
fi
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm \
  -v "$RELEASE_DIR:/artifacts:ro" backend-migrate \
  python scripts/legacy_backfill_gate.py plan \
  --inventory /artifacts/uploads-inventory.json \
  --dry-run /artifacts/uploads-migrate-dry-run.json \
  | tee "$RELEASE_DIR/uploads-backfill-plan.json"; then
  echo '生产历史文件计划不一致' >&2
  exit 1
fi
PRODUCTION_BACKFILL_ACTION="$(jq -er '.action' "$RELEASE_DIR/uploads-backfill-plan.json")"
PRODUCTION_BACKFILL_PENDING="$(jq -er '.pending' "$RELEASE_DIR/uploads-backfill-plan.json")"
if [[ "$PRODUCTION_BACKFILL_ACTION" == "migrate" ]]; then
  if docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm backend-migrate \
    python scripts/backfill_legacy_uploads.py verify \
    | tee "$RELEASE_DIR/uploads-verify-before.json"; then
    echo '生产存在pending时verify意外成功' >&2
    exit 1
  fi
  if ! jq -e --argjson expected "$PRODUCTION_BACKFILL_PENDING" \
    '.schema == "ai-interview.legacy-upload-backfill" and .ok == false and .counts.pending == $expected and .counts.errors == 0' \
    "$RELEASE_DIR/uploads-verify-before.json" >/dev/null; then
    echo '生产迁移前verify不是预期pending失败' >&2
    exit 1
  fi
  if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm backend-migrate \
    python scripts/backfill_legacy_uploads.py migrate \
    | tee "$RELEASE_DIR/uploads-migrate.json"; then
    echo '生产历史文件迁移失败' >&2
    exit 1
  fi
  if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm \
    -v "$RELEASE_DIR:/artifacts:ro" backend-migrate \
    python scripts/legacy_backfill_gate.py finalize \
    --plan /artifacts/uploads-backfill-plan.json \
    --migration /artifacts/uploads-migrate.json \
    | tee "$RELEASE_DIR/uploads-backfill-result.json"; then
    echo '生产实际迁移数与pending不一致' >&2
    exit 1
  fi
else
  if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm backend-migrate \
    python scripts/backfill_legacy_uploads.py verify \
    | tee "$RELEASE_DIR/uploads-verify-before.json"; then
    echo '生产零pending时verify失败' >&2
    exit 1
  fi
  if ! jq -e \
    '.schema == "ai-interview.legacy-upload-backfill" and .ok == true and .counts.pending == 0 and .counts.errors == 0' \
    "$RELEASE_DIR/uploads-verify-before.json" >/dev/null; then
    echo '生产零pending校验JSON异常' >&2
    exit 1
  fi
  if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm \
    -v "$RELEASE_DIR:/artifacts:ro" backend-migrate \
    python scripts/legacy_backfill_gate.py finalize \
    --plan /artifacts/uploads-backfill-plan.json \
    | tee "$RELEASE_DIR/uploads-backfill-result.json"; then
    echo '生产零pending收尾失败' >&2
    exit 1
  fi
fi
PRODUCTION_STORED_FILE_INCREASE="$(jq -er \
  '.stored_files_increase' "$RELEASE_DIR/uploads-backfill-result.json")"
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm backend-migrate \
  python scripts/backfill_legacy_uploads.py verify \
  | tee "$RELEASE_DIR/uploads-verify-after.json"; then
  echo '生产历史文件迁移后验证失败' >&2
  exit 1
fi
if ! jq -e \
  '.schema == "ai-interview.legacy-upload-backfill" and .ok == true and .counts.pending == 0 and .counts.errors == 0' \
  "$RELEASE_DIR/uploads-verify-after.json" >/dev/null; then
  echo '生产最终历史文件JSON门禁失败' >&2
  exit 1
fi
```

第一次 `verify` 在仍有待迁移文件时应返回非零；最终 `verify` 必须返回零。逐项处理所有拒绝项，核对迁移前后文件内容哈希，并保留旧文件直至观察期结束。重复执行 `migrate` 应显示无新的候选项。

### 4.4 启用 RLS 并完成枚举迁移

```bash
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm backend-migrate \
  alembic upgrade head; then
  echo '生产head迁移失败' >&2
  exit 1
fi
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm postgres-finalize; then
  echo '生产运行角色权限收敛失败' >&2
  exit 1
fi
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm \
  backend-migrate python scripts/verify_database_permissions.py \
  | tee "$RELEASE_DIR/production-database-permissions.json"; then
  echo '生产数据库权限门禁失败' >&2
  exit 1
fi
```

此阶段会把 18 个租户表设置为强制 RLS，并对 29 组租户复合引用建立约束。`postgres-finalize` 必须撤销运行角色不需要的权限。权限 JSON 必须显示 `session_identity_valid=true`、`application_role_memberships=0`，以及 23 张应用表的精确 DML；否则不得启动后端。

使用迁移角色核对强制 RLS 和租户复合外键数量，结果必须分别为 18 和 29：

```bash
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec -T postgres \
  env PGPASSWORD="$APP_MIGRATION_PASSWORD" \
  psql -U app_migration -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace AND relname = ANY(ARRAY['users','positions','question_banks','resumes','department_reviews','interviews','interview_panels','offers','offer_templates','coding_tests','coding_submissions','system_configs','workflows','workflow_nodes','workflow_edges','workflow_executions','workflow_node_executions','stored_files']) AND relrowsecurity AND relforcerowsecurity" \
  | grep -qx '18'; then
  echo '生产FORCE RLS数量不是18' >&2
  exit 1
fi
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec -T postgres \
  env PGPASSWORD="$APP_MIGRATION_PASSWORD" \
  psql -U app_migration -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM pg_constraint WHERE contype='f' AND conname LIKE 'fk_%_tenant' AND array_length(conkey,1)=2" \
  | grep -qx '29'; then
  echo '生产复合外键数量不是29' >&2
  exit 1
fi
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm -T \
  backend-migrate python - <<'PY'
from sqlalchemy import create_engine, text
from app.models.base import Base
import os
expected = {}
for table in Base.metadata.sorted_tables:
    for column in table.columns:
        labels = getattr(column.type, "enums", None)
        if labels and getattr(column.type, "native_enum", False):
            expected.setdefault(column.type.name, set()).update(labels)
engine = create_engine(os.environ["MIGRATION_DATABASE_URL"])
with engine.connect() as connection:
    rows = connection.execute(text("SELECT t.typname,e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid=t.oid JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public'"))
    actual = {}
    for name, label in rows:
        actual.setdefault(name, set()).add(label)
assert actual == expected, "native enum labels do not match runtime metadata"
PY
then
  echo '生产枚举标签检查失败' >&2
  exit 1
fi
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm backend-migrate \
  alembic current | tee "$RELEASE_DIR/production-alembic-current-after.txt"; then
  echo '生产Alembic head检查失败' >&2
  exit 1
fi
grep -q 'r7s8t9u0v1w2' "$RELEASE_DIR/production-alembic-current-after.txt" \
  || { echo '生产库不在Alembic head' >&2; exit 1; }
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm \
  -v "$RELEASE_DIR:/artifacts" backend-migrate \
  python scripts/snapshot_tenant_counts.py snapshot \
  --json /artifacts/production-counts-after.json \
  --csv /artifacts/production-counts-after.csv; then
  echo '生产迁移后18表快照失败' >&2
  exit 1
fi
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm \
  -v "$RELEASE_DIR:/artifacts:ro" backend-migrate \
  python scripts/snapshot_tenant_counts.py compare \
  --before /artifacts/production-counts-before.json \
  --after /artifacts/production-counts-after.json \
  --allow-stored-files-increase "$PRODUCTION_STORED_FILE_INCREASE" \
  | tee "$RELEASE_DIR/production-count-comparison.json"; then
  echo '生产18表逐表机器比较失败' >&2
  exit 1
fi
```

### 4.5 运行迁移校验门禁

后端仍需保持停止。校验器只接受 `MIGRATION_DATABASE_URL`，会在单个事务中短暂执行 `NO FORCE RLS` 并在回滚时恢复。不得改用 `DATABASE_URL` 或管理账号。

```bash
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm backend-migrate \
  python scripts/verify_tenant_migration.py \
  | tee "$RELEASE_DIR/tenant-verification.json"; then
  echo '生产租户迁移校验器失败' >&2
  exit 1
fi
if ! jq -e '.ok == true' "$RELEASE_DIR/tenant-verification.json" >/dev/null; then
  echo '生产租户迁移校验JSON不是ok=true' >&2
  exit 1
fi
```

只有 JSON 中 `ok=true`、18 个租户表空租户计数均为零、29 组跨租户/缺失父项均为零、配置和历史文件检查均通过时才能继续。输出不得出现连接串或密码。

## 5. 平台管理员与 Photonthix 入驻

平台管理员脚本幂等；已有同邮箱管理员不会被重置密码。通过交互式读取避免密码进入命令历史：

```bash
read -r -p '平台管理员邮箱: ' PLATFORM_ADMIN_EMAIL
read -r -s -p '平台管理员密码: ' PLATFORM_ADMIN_PASSWORD; echo
export PLATFORM_ADMIN_EMAIL PLATFORM_ADMIN_PASSWORD
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm \
  -e PLATFORM_ADMIN_EMAIL -e PLATFORM_ADMIN_PASSWORD \
  backend-migrate python scripts/create_platform_admin.py
unset PLATFORM_ADMIN_PASSWORD
```

平台管理员忘记密码时，在部署目录执行一条命令：

```bash
make reset-platform-admin-password
```

命令会自动构建包含维护脚本的后端镜像，并隐藏输入新密码两次。若系统中只有一个平台管理员，脚本会自动识别邮箱；存在多个账号时，为避免重置错误账号会安全失败。脚本不会创建账号或自动启用已停用账号。看到“平台管理员密码已修改”才视为成功。现有平台令牌最长仍可使用 60 分钟。

启动后端和前端，先不开放外部流量：

```bash
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml up -d backend frontend
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml ps
```

平台控制面也必须经过正式 Caddy HTTPS 入口。先校验并启动 Caddy，等待内部 CA 根证书可导出；不得为了初始化而临时绕过 Host 策略或改走回环 HTTP：

```bash
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm --no-deps caddy \
  caddy validate --config /etc/caddy/Caddyfile
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml up -d caddy
CADDY_CA_READY=0
for attempt in $(seq 1 30); do
  if docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec -T caddy \
    test -s /data/caddy/pki/authorities/local/root.crt; then
    CADDY_CA_READY=1
    break
  fi
  sleep 1
done
if [ "$CADDY_CA_READY" -ne 1 ]; then
  echo 'Caddy内部CA根证书在30秒内未就绪' >&2
  exit 1
fi
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml cp \
  caddy:/data/caddy/pki/authorities/local/root.crt \
  "$RELEASE_DIR/ai-interview-caddy-root.crt"
```

使用受信 CA 和正式域名登录平台 API 并入驻 Photonthix。令牌和管理员密码仅存在当前 shell 变量中：

```bash
read -r -p '平台管理员邮箱: ' PLATFORM_ADMIN_EMAIL
read -r -s -p '平台管理员密码: ' PLATFORM_ADMIN_PASSWORD; echo
PLATFORM_TOKEN="$(curl --fail --silent --show-error \
  --cacert "$RELEASE_DIR/ai-interview-caddy-root.crt" \
  --resolve "interview.careray.com:443:$SERVER_IP" \
  -H 'Content-Type: application/json' \
  --data "$(jq -n --arg e "$PLATFORM_ADMIN_EMAIL" --arg p "$PLATFORM_ADMIN_PASSWORD" '{email:$e,password:$p}')" \
  https://interview.careray.com/api/platform/auth/login | jq -r '.access_token')"
unset PLATFORM_ADMIN_PASSWORD

read -r -s -p 'Photonthix 初始管理员密码: ' PHOTONTHIX_ADMIN_PASSWORD; echo
curl --fail --silent --show-error \
  --cacert "$RELEASE_DIR/ai-interview-caddy-root.crt" \
  --resolve "interview.careray.com:443:$SERVER_IP" \
  -H "Authorization: Bearer $PLATFORM_TOKEN" \
  -H 'Content-Type: application/json' \
  --data "$(jq -n --arg p "$PHOTONTHIX_ADMIN_PASSWORD" '{code:"photonthix",name:"Photonthix",admin_email:"<photonthix-admin-email>",admin_password:$p}')" \
  https://interview.careray.com/api/platform/tenants
unset PHOTONTHIX_ADMIN_PASSWORD
```

若 Photonthix 已存在，先通过平台查询接口核对状态，不要重复创建或直接改库。

平台管理员可通过以下控制面接口核对租户。所有租户统一使用 `interview.careray.com`，控制面不再登记或维护公司域名：

```text
GET    /api/platform/tenants
GET    /api/platform/tenants/{tenant_id}
```

## 6. 内部域名、HTTPS 与麦克风

应用进程对登录、公开简历上传、公开代码试运行、代码正式提交和作文 AI 评估分别执行分钟级限流，并可通过 `RATE_LIMIT_LOGIN`、`RATE_LIMIT_PUBLIC_UPLOAD`、`RATE_LIMIT_PUBLIC_CODE_RUN`、`RATE_LIMIT_PUBLIC_CODE_SUBMIT`、`RATE_LIMIT_PUBLIC_ESSAY_SUBMIT` 调整单进程阈值。公开简历上传的主体桶使用“租户+职位+规范化候选人信息”的不可逆哈希，并同时保留客户端 IP 桶；`RATE_LIMIT_PUBLIC_UPLOAD_TENANT` 是独立的租户分钟总成本上限，默认值应显著高于单候选人阈值。每次请求同时消耗客户端 IP 配额和账号/公开令牌配额，任一配额耗尽都会在业务执行前返回 429；内存桶由 `RATE_LIMIT_MAX_BUCKETS` 设定上限，并按 TTL/LRU 淘汰。该内存限流只承担应用最后一道防线，不是集群级防护。生产入口还必须在受信网关/WAF 按客户端 IP 与路径配置独立阈值和突发容量，并限制请求体大小；多副本部署时网关计数必须集中共享。后端只在直接对端属于 `TRUSTED_PROXY_CIDRS` 时从右向左验证 `X-Forwarded-For`，链中格式错误时退回直接对端；禁止直接信任公网请求提供的转发头。`TRUSTED_PROXY_CIDRS` 中任何无效 CIDR 都会阻止应用启动，必须先修正配置，禁止静默忽略。429 比例、拒绝路径和重试间隔必须纳入监控，但不得记录登录密码、JWT、公开令牌或代码正文。

生产后端必须以 `uvicorn --no-access-log` 启动；Nginx 对 `/api/public/` 以及三类公开 SPA 入口禁用访问日志，并把这些 location 的上游错误日志丢弃，应用自身只记录不含参数的路由模板和脱敏后的结构化字段。发布前必须运行 `scripts/verify-nginx-token-logs.sh`，用真实 Nginx 请求覆盖 coding-test、offer、review 的 SPA/API 路径和上游失败，确认哨兵 token 不会出现在 Uvicorn、Nginx 或应用日志中，同时保留非公开请求的状态码、request ID、租户、任务和资源上下文。

内部 DNS 必须把统一入口 `interview.careray.com` 解析到受控服务器。

Caddy 配置使用内部 CA，站点块必须包含 `tls internal`，为统一入口域名提供 HTTPS。启动前先校验配置，再导出根证书：

```bash
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm --no-deps caddy \
  caddy validate --config /etc/caddy/Caddyfile; then
  echo 'Caddy配置校验失败' >&2
  exit 1
fi
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml up -d caddy; then
  echo 'Caddy启动失败' >&2
  exit 1
fi
CADDY_CA_READY=0
for attempt in $(seq 1 30); do
  if docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec -T caddy \
    test -s /data/caddy/pki/authorities/local/root.crt; then
    CADDY_CA_READY=1
    break
  fi
  sleep 1
done
if [ "$CADDY_CA_READY" -ne 1 ]; then
  echo 'Caddy内部CA根证书在30秒内未就绪' >&2
  exit 1
fi
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml cp \
  caddy:/data/caddy/pki/authorities/local/root.crt \
  "$RELEASE_DIR/ai-interview-caddy-root.crt"; then
  echo 'Caddy根证书导出失败' >&2
  exit 1
fi
if ! sha256sum "$RELEASE_DIR/ai-interview-caddy-root.crt" \
  > "$RELEASE_DIR/ai-interview-caddy-root.crt.sha256"; then
  echo 'Caddy根证书校验和生成失败' >&2
  exit 1
fi
```

通过企业设备管理把该根证书安装到受控客户端的“受信任根证书颁发机构”，并核对指纹。不得通过聊天工具让用户忽略证书警告。验证统一入口域名、证书链和 Host 透传：

```bash
curl --fail --show-error --cacert "$RELEASE_DIR/ai-interview-caddy-root.crt" \
  --resolve "interview.careray.com:443:$SERVER_IP" \
  https://interview.careray.com/api/auth/tenants
```

浏览器控制台必须显示 `window.isSecureContext === true`。检查响应包含限制到本站的 `Permissions-Policy: microphone=(self)`，在统一入口授权麦克风，实际录制、上传并回放一段无敏感内容的音频。HTTP、证书告警或麦克风失败都属于发布阻断项。

## 7. 业务与隔离验收

### 7.1 登录与租户隔离

为两个租户分别创建同邮箱、不同密码的测试用户。每个用户只能用正确 `tenant_code` 和自己的密码登录；错误租户或另一租户的密码必须失败。

```bash
curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  --data '{"tenant_code":"careray","email":"<shared-test-email>","password":"<careray-test-password>"}' \
  https://interview.careray.com/api/auth/login
curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  --data '{"tenant_code":"photonthix","email":"<shared-test-email>","password":"<photonthix-test-password>"}' \
  https://interview.careray.com/api/auth/login
```

分别建立职位、简历、面试、Offer、编程题、工作流和配置，确认列表、仪表盘与文件下载互不可见。对运行角色做数据库负向检查，在事务中设置一个租户后查询另一个租户，结果必须为零：

```bash
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec -T postgres \
  env PGPASSWORD="$APP_RUNTIME_PASSWORD" \
  psql -U app_runtime -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
SET LOCAL app.current_tenant_id = '<careray-tenant-uuid>';
SELECT count(*) AS must_be_zero
FROM users WHERE tenant_id = '<photonthix-tenant-uuid>';
ROLLBACK;
SQL
```

检查公开面试链接只在数据库保存 64 位十六进制哈希，不得保存原始令牌，并验证令牌只能打开其所属租户的面试。对文件接口请求编码后的目录穿越路径必须返回 4xx，且日志中不得出现文件内容：

```bash
curl --path-as-is --fail-with-body \
  'https://interview.careray.com/uploads/%2e%2e/%2e%2e/<protected-file>'
```

### 7.2 禁用租户

由平台管理员把 Careray 临时置为禁用状态，确认新登录失败、此前签发的 JWT 访问业务 API 返回 403、后台任务不会更新数据；随后恢复为启用状态并再次验证。这个动作必须在业务验收人同意的窗口内完成，禁止直接更新数据库绕过审计。

### 7.3 SMTP、LLM、FFmpeg 与后台任务

使用各租户管理员令牌向真实、受控的测试邮箱发送邮件：

```bash
curl --fail --silent --show-error \
  -H "Authorization: Bearer <tenant-admin-token>" \
  -H 'Content-Type: application/json' \
  --data '{"recipient":"<real-test-recipient>"}' \
  https://interview.careray.com/api/settings/mail/test
```

SMTP SSL 通常使用 465，STARTTLS/TLS 通常使用 587；API 成功不等于投递完成，必须在真实收件箱确认到达，并检查没有跨租户使用邮件配置。

使用无敏感信息的测试简历和题目完成一次 LLM 解析、面试提问与评分，确认模型、超时、错误脱敏和租户配置。验证容器内 FFmpeg：

```bash
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec backend ffmpeg -version
```

当前后台任务是后端进程内线程池，不是独立持久队列。发布初期只运行一个 Uvicorn 进程；在引入外部持久队列前，不得依赖多进程抢占或容器重启后的任务恢复。观察解析、评分和音频任务直到完成，检查错误租户任务不更新数据、失败会落日志且不会泄露密钥。

## 8. 监控、审计与放行门禁

至少观察一个完整业务高峰，并持续记录：

- 两域名的 HTTPS、证书到期、5xx、401/403 和请求延迟。
- PostgreSQL 连接、锁等待、RLS 拒绝、约束错误、磁盘与备份状态。
- 登录失败、平台管理员操作、租户创建/禁用/恢复和配置变更审计。
- LLM/SMTP/FFmpeg/后台任务成功率、耗时和脱敏错误。
- `backend_uploads` 容量、缺失文件、拒绝的历史路径和文件下载 4xx。

最终放行必须同时满足：备份异机校验和通过；恢复演练达到 RTO/RPO；Alembic 在 `head`；迁移校验器 `ok=true`；最终历史文件 `verify` 返回零；18 个表强制 RLS、29 组复合引用存在；两个租户的正向流程成功、交叉访问全部失败；同邮箱不同密码正确隔离；公开令牌只保存哈希；禁用租户阻止新旧令牌；HTTPS、麦克风、真实 SMTP、LLM、FFmpeg 和后台任务通过；监控与审计可用。任一项失败都不得开放流量。

放行后重新记录关键表行数，并与发布前快照解释性对比。租户补全和 StoredFile 建立会增加部分表行数，但不得丢失原有业务行或文件。

## 9. 应用回滚

旧应用不认识强制 RLS。回滚顺序必须是：停止新应用，先取消 RLS 策略，再启动旧应用。反过来会导致旧应用看到空数据或写入失败。

```bash
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml stop backend frontend caddy
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec -T postgres \
  env PGPASSWORD="$APP_MIGRATION_PASSWORD" \
  psql -U app_migration -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
SELECT format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY;', table_name)
FROM unnest(ARRAY[
  'users','positions','question_banks','resumes','department_reviews','interviews',
  'interview_panels','offers','offer_templates','coding_tests','coding_submissions',
  'system_configs','workflows','workflow_nodes','workflow_edges','workflow_executions',
  'workflow_node_executions','stored_files'
]) AS table_name \gexec
SELECT format('DROP POLICY IF EXISTS %I ON %I;', table_name || '_tenant_isolation', table_name)
FROM unnest(ARRAY[
  'users','positions','question_banks','resumes','department_reviews','interviews',
  'interview_panels','offers','offer_templates','coding_tests','coding_submissions',
  'system_configs','workflows','workflow_nodes','workflow_edges','workflow_executions',
  'workflow_node_executions','stored_files'
]) AS table_name \gexec
SELECT format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY;', table_name)
FROM unnest(ARRAY[
  'users','positions','question_banks','resumes','department_reviews','interviews',
  'interview_panels','offers','offer_templates','coding_tests','coding_submissions',
  'system_configs','workflows','workflow_nodes','workflow_edges','workflow_executions',
  'workflow_node_executions','stored_files'
]) AS table_name \gexec
COMMIT;
SQL
```

把 Compose 中后端和前端镜像固定回已记录的旧摘要，执行 `docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml up -d backend frontend caddy`，再做旧版健康检查。不要删除 `tenant_id`、租户表、StoredFile、复合外键或新增枚举值；保留这些向前兼容的数据，待修复后重发。绝对不要执行 `docker compose down -v`。

如果应用回滚仍不能恢复服务，进入灾难恢复：在新的空数据库和新的上传卷中恢复“停止写入后”的数据库归档和文件归档，完整核对后再原子切换连接或 Compose 项目。不要覆盖当前生产库/卷，以便取证和二次恢复。记录从故障到恢复服务的实际 RTO，以及从最后一致性备份到故障点的实际 RPO；若超过目标立即升级事故等级。

## 10. 发布后收尾

观察期结束前保留数据库归档、上传归档、旧文件、迁移 JSON、镜像摘要和审计日志。确认稳定后按公司的保留策略清理，而不是删除 Docker 卷。关闭临时测试账号、撤销临时令牌和不再需要的证书分发权限，补齐发布结论、实际 RTO/RPO、遗留项和负责人。
