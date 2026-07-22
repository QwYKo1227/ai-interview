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
export RELEASE_ID='<YYYYMMDD-HHMM-commit>'
export RELEASE_DIR='/srv/ai-interview/releases/'"$RELEASE_ID"
export SERVER_IP='<internal-server-ip>'
export BACKUP_HOST='<off-host-backup-host>'
export BACKUP_DIR='<off-host-backup-directory>'
export EXPECTED_RTO_MINUTES='<RTO-minutes>'
export EXPECTED_RPO_MINUTES='<RPO-minutes>'
mkdir -p "$RELEASE_DIR"
```

检查 `.env`，不要输出其内容：

- `POSTGRES_PASSWORD`、`APP_RUNTIME_PASSWORD`、`APP_MIGRATION_PASSWORD` 使用不同强密码。
- `DATABASE_URL` 只能使用 `app_runtime`；`MIGRATION_DATABASE_URL` 只能使用 `app_migration`。
- `SECRET_KEY` 已安全生成，且与旧环境的令牌处理策略一致。
- `APP_ENV=production`。
- `APP_DOMAINS=interview.careray.com, interview.photonthix.com`。
- `CORS_ORIGINS=https://interview.careray.com,https://interview.photonthix.com`。
- LLM 和 SMTP 密钥通过受控密钥系统注入，未提交到仓库。
- 后端镜像使用已验收且不可变的版本或摘要；记录摘要到发布工单。

让当前受控 shell 读取 `.env`，供下文命令使用；整个会话禁止启用命令回显：

```bash
set -o pipefail
set -a
. ./.env
set +a
```

## 2. 备份与恢复演练

### 2.1 数据库归档、校验和与异机保存

先确认生产仍在运行并记录备份开始时间。使用 PostgreSQL 自定义格式归档：

```bash
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
  > "$RELEASE_DIR/database-before.dump"
sha256sum "$RELEASE_DIR/database-before.dump" \
  | tee "$RELEASE_DIR/database-before.dump.sha256"
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
sha256sum "$RELEASE_DIR/uploads-before.tar.gz" \
  | tee "$RELEASE_DIR/uploads-before.tar.gz.sha256"
scp "$RELEASE_DIR/uploads-before.tar.gz" \
  "$RELEASE_DIR/uploads-before.tar.gz.sha256" \
  "$BACKUP_HOST:$BACKUP_DIR/"
ssh "$BACKUP_HOST" "cd '$BACKUP_DIR' && sha256sum -c uploads-before.tar.gz.sha256"
```

卷名可能带有不同的 Compose 项目前缀，先用 `docker volume ls` 确认实际的 `backend_uploads` 卷名，再替换命令中的占位值。

### 2.3 在克隆环境恢复演练

禁止把演练恢复到生产库或生产卷。创建隔离的数据库克隆和空目录，然后恢复：

```bash
createdb '<restore-drill-database>'
pg_restore --clean --if-exists --no-owner \
  -d '<restore-drill-database>' "$RELEASE_DIR/database-before.dump"
mkdir -p "$RELEASE_DIR/restore-drill-uploads"
tar -xzf "$RELEASE_DIR/uploads-before.tar.gz" \
  -C "$RELEASE_DIR/restore-drill-uploads"
```

在克隆库中执行 `SELECT count(*)` 核对关键表，并随机打开简历、题库源文件和面试音频。记录恢复开始、数据库可用、文件可用的时间；实测恢复耗时必须小于 RTO。RPO 是最后一份一致性备份与故障时刻之间可能丢失的数据时间，本次维护窗口内的 RPO 由停止写入后的最终备份时间决定。把实测 RTO/RPO 写入发布工单；不满足目标不得发布。

## 3. 发布前快照和停止写入

记录当前版本、容器和行数，输出只保存到受控发布目录：

```bash
git rev-parse HEAD | tee "$RELEASE_DIR/source-commit.txt"
docker compose -f docker-compose.prod.yml images \
  | tee "$RELEASE_DIR/images-before.txt"
docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -c "SELECT 'users' AS table_name,count(*) FROM users UNION ALL SELECT 'positions',count(*) FROM positions UNION ALL SELECT 'resumes',count(*) FROM resumes UNION ALL SELECT 'interviews',count(*) FROM interviews UNION ALL SELECT 'offers',count(*) FROM offers UNION ALL SELECT 'question_banks',count(*) FROM question_banks;" \
  | tee "$RELEASE_DIR/row-counts-before.txt"
```

宣布维护窗口，禁止新登录和写入，然后停止会写数据库的应用容器：

```bash
docker compose -f docker-compose.prod.yml stop backend frontend caddy
docker compose -f docker-compose.prod.yml ps
```

确认没有应用连接和未完成事务后，再做一份“停止写入后”的最终数据库与文件备份，重复第 2 节的校验和及异机上传步骤。后续所有阶段出现不可解释差异时立即停止，不要尝试带病继续。

## 4. 分阶段兼容升级

### 4.1 启动数据库角色并检查迁移链

```bash
docker compose -f docker-compose.prod.yml up -d postgres
docker compose -f docker-compose.prod.yml run --rm postgres-init
docker compose -f docker-compose.prod.yml run --rm backend-migrate \
  alembic current
docker compose -f docker-compose.prod.yml run --rm backend-migrate \
  alembic heads
```

`postgres-init` 必须成功建立受限的 `app_runtime` 和 DDL 专用的 `app_migration`。任何时候都不得让后端使用 PostgreSQL 管理账号。

### 4.2 只升级到租户文件兼容阶段

先执行租户基础和存储文件迁移，但暂不启用强制 RLS：

```bash
docker compose -f docker-compose.prod.yml run --rm backend-migrate \
  alembic upgrade m2n3o4p5q6r7
```

检查 Careray 已成为既有数据的默认租户，所有租户表 `tenant_id` 均无空值，复合外键没有跨租户引用。同一租户内的用户邮箱必须大小写不敏感唯一；不同租户允许同邮箱。

### 4.3 盘点、演练并迁移历史上传

历史字段包括简历 `file_path/file_id`、题库 `source_file/source_file_id` 和面试音频 JSON。迁移工具只复制并原子落盘，不删除旧文件。缺失、软链接、目录穿越或不属于当前租户的路径会被拒绝。

```bash
docker compose -f docker-compose.prod.yml run --rm backend-migrate \
  python scripts/backfill_legacy_uploads.py inventory --dry-run \
  | tee "$RELEASE_DIR/uploads-inventory.json"
if docker compose -f docker-compose.prod.yml run --rm backend-migrate \
  python scripts/backfill_legacy_uploads.py verify \
  | tee "$RELEASE_DIR/uploads-verify-before.json"; then
  echo '迁移前 verify 意外成功，请停止并检查盘点结果' >&2
  exit 1
fi
docker compose -f docker-compose.prod.yml run --rm backend-migrate \
  python scripts/backfill_legacy_uploads.py migrate --dry-run \
  | tee "$RELEASE_DIR/uploads-migrate-dry-run.json"
docker compose -f docker-compose.prod.yml run --rm backend-migrate \
  python scripts/backfill_legacy_uploads.py migrate \
  | tee "$RELEASE_DIR/uploads-migrate.json"
docker compose -f docker-compose.prod.yml run --rm backend-migrate \
  python scripts/backfill_legacy_uploads.py verify \
  | tee "$RELEASE_DIR/uploads-verify-after.json"
```

第一次 `verify` 在仍有待迁移文件时应返回非零；最终 `verify` 必须返回零。逐项处理所有拒绝项，核对迁移前后文件内容哈希，并保留旧文件直至观察期结束。重复执行 `migrate` 应显示无新的候选项。

### 4.4 启用 RLS 并完成枚举迁移

```bash
docker compose -f docker-compose.prod.yml run --rm backend-migrate \
  alembic upgrade head
docker compose -f docker-compose.prod.yml run --rm postgres-finalize
```

此阶段会把 18 个租户表设置为强制 RLS，并对 29 组租户复合引用建立约束。`postgres-finalize` 必须撤销运行角色不需要的权限。

使用迁移角色核对强制 RLS 和租户复合外键数量，结果必须分别为 18 和 29：

```bash
docker compose -f docker-compose.prod.yml exec -T postgres \
  env PGPASSWORD="$APP_MIGRATION_PASSWORD" \
  psql -U app_migration -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<'SQL'
SELECT count(*) AS force_rls_tables
FROM pg_class
WHERE relnamespace = 'public'::regnamespace
  AND relname = ANY(ARRAY[
    'users','positions','question_banks','resumes','department_reviews','interviews',
    'interview_panels','offers','offer_templates','coding_tests','coding_submissions',
    'system_configs','workflows','workflow_nodes','workflow_edges','workflow_executions',
    'workflow_node_executions','stored_files'
  ])
  AND relrowsecurity AND relforcerowsecurity;

SELECT count(*) AS composite_tenant_foreign_keys
FROM pg_constraint child_fk
JOIN pg_class child ON child.oid = child_fk.conrelid
JOIN pg_attribute child_tenant
  ON child_tenant.attrelid = child.oid
 AND child_tenant.attname = 'tenant_id'
JOIN pg_class parent ON parent.oid = child_fk.confrelid
JOIN pg_attribute parent_tenant
  ON parent_tenant.attrelid = parent.oid
 AND parent_tenant.attname = 'tenant_id'
WHERE child_fk.contype = 'f'
  AND child_tenant.attnum = ANY(child_fk.conkey)
  AND parent_tenant.attnum = ANY(child_fk.confkey);
SQL
```

### 4.5 运行迁移校验门禁

后端仍需保持停止。校验器只接受 `MIGRATION_DATABASE_URL`，会在单个事务中短暂执行 `NO FORCE RLS` 并在回滚时恢复。不得改用 `DATABASE_URL` 或管理账号。

```bash
docker compose -f docker-compose.prod.yml run --rm backend-migrate \
  python scripts/verify_tenant_migration.py \
  | tee "$RELEASE_DIR/tenant-verification.json"
test "$(jq -r '.ok' "$RELEASE_DIR/tenant-verification.json")" = 'true'
```

只有 JSON 中 `ok=true`、18 个租户表空租户计数均为零、29 组跨租户/缺失父项均为零、配置和历史文件检查均通过时才能继续。输出不得出现连接串或密码。

## 5. 平台管理员与 Photonthix 入驻

平台管理员脚本幂等；已有同邮箱管理员不会被重置密码。通过交互式读取避免密码进入命令历史：

```bash
read -r -p '平台管理员邮箱: ' PLATFORM_ADMIN_EMAIL
read -r -s -p '平台管理员密码: ' PLATFORM_ADMIN_PASSWORD; echo
export PLATFORM_ADMIN_EMAIL PLATFORM_ADMIN_PASSWORD
docker compose -f docker-compose.prod.yml run --rm \
  -e PLATFORM_ADMIN_EMAIL -e PLATFORM_ADMIN_PASSWORD \
  backend-migrate python scripts/create_platform_admin.py
unset PLATFORM_ADMIN_PASSWORD
```

启动后端和前端，先不开放外部流量：

```bash
docker compose -f docker-compose.prod.yml up -d backend frontend
docker compose -f docker-compose.prod.yml ps
```

使用平台 API 登录并入驻 Photonthix。令牌和管理员密码仅存在当前 shell 变量中：

```bash
read -r -p '平台管理员邮箱: ' PLATFORM_ADMIN_EMAIL
read -r -s -p '平台管理员密码: ' PLATFORM_ADMIN_PASSWORD; echo
PLATFORM_TOKEN="$(curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  --data "$(jq -n --arg e "$PLATFORM_ADMIN_EMAIL" --arg p "$PLATFORM_ADMIN_PASSWORD" '{email:$e,password:$p}')" \
  http://127.0.0.1/api/platform/auth/login | jq -r '.access_token')"
unset PLATFORM_ADMIN_PASSWORD

read -r -s -p 'Photonthix 初始管理员密码: ' PHOTONTHIX_ADMIN_PASSWORD; echo
curl --fail --silent --show-error \
  -H "Authorization: Bearer $PLATFORM_TOKEN" \
  -H 'Content-Type: application/json' \
  --data "$(jq -n --arg p "$PHOTONTHIX_ADMIN_PASSWORD" '{code:"photonthix",name:"Photonthix",primary_domain:"interview.photonthix.com",admin_email:"<photonthix-admin-email>",admin_password:$p}')" \
  http://127.0.0.1/api/platform/tenants
unset PHOTONTHIX_ADMIN_PASSWORD
```

若 Photonthix 已存在，先通过平台查询接口核对状态，不要重复创建或直接改库。

## 6. 内部域名、HTTPS 与麦克风

内部 DNS 必须把以下两个名称解析到同一台受控服务器：

- `interview.careray.com`
- `interview.photonthix.com`

Caddy 配置使用内部 CA，站点块必须包含 `tls internal`，为两个域名自动提供 HTTPS。启动前先校验配置，再导出根证书：

```bash
docker compose -f docker-compose.prod.yml run --rm --no-deps caddy \
  caddy validate --config /etc/caddy/Caddyfile
docker compose -f docker-compose.prod.yml up -d caddy
docker compose -f docker-compose.prod.yml cp \
  caddy:/data/caddy/pki/authorities/local/root.crt \
  "$RELEASE_DIR/ai-interview-caddy-root.crt"
sha256sum "$RELEASE_DIR/ai-interview-caddy-root.crt"
```

通过企业设备管理把该根证书安装到受控客户端的“受信任根证书颁发机构”，并核对指纹。不得通过聊天工具让用户忽略证书警告。验证两个域名、证书链和 Host 透传：

```bash
curl --fail --show-error --cacert "$RELEASE_DIR/ai-interview-caddy-root.crt" \
  --resolve "interview.careray.com:443:$SERVER_IP" \
  https://interview.careray.com/api/auth/tenants
curl --fail --show-error --cacert "$RELEASE_DIR/ai-interview-caddy-root.crt" \
  --resolve "interview.photonthix.com:443:$SERVER_IP" \
  https://interview.photonthix.com/api/auth/tenants
```

浏览器控制台必须显示 `window.isSecureContext === true`。检查响应包含限制到本站的 `Permissions-Policy: microphone=(self)`，在两域名分别授权麦克风，实际录制、上传并回放一段无敏感内容的音频。HTTP、证书告警或麦克风失败都属于发布阻断项。

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
  https://interview.photonthix.com/api/auth/login
```

分别建立职位、简历、面试、Offer、编程题、工作流和配置，确认列表、仪表盘与文件下载互不可见。对运行角色做数据库负向检查，在事务中设置一个租户后查询另一个租户，结果必须为零：

```bash
docker compose -f docker-compose.prod.yml exec -T postgres \
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
docker compose -f docker-compose.prod.yml exec backend ffmpeg -version
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
docker compose -f docker-compose.prod.yml stop backend frontend caddy
docker compose -f docker-compose.prod.yml exec -T postgres \
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

把 Compose 中后端和前端镜像固定回已记录的旧摘要，执行 `docker compose -f docker-compose.prod.yml up -d backend frontend caddy`，再做旧版健康检查。不要删除 `tenant_id`、租户表、StoredFile、复合外键或新增枚举值；保留这些向前兼容的数据，待修复后重发。绝对不要执行 `docker compose down -v`。

如果应用回滚仍不能恢复服务，进入灾难恢复：在新的空数据库和新的上传卷中恢复“停止写入后”的数据库归档和文件归档，完整核对后再原子切换连接或 Compose 项目。不要覆盖当前生产库/卷，以便取证和二次恢复。记录从故障到恢复服务的实际 RTO，以及从最后一致性备份到故障点的实际 RPO；若超过目标立即升级事故等级。

## 10. 发布后收尾

观察期结束前保留数据库归档、上传归档、旧文件、迁移 JSON、镜像摘要和审计日志。确认稳定后按公司的保留策略清理，而不是删除 Docker 卷。关闭临时测试账号、撤销临时令牌和不再需要的证书分发权限，补齐发布结论、实际 RTO/RPO、遗留项和负责人。
