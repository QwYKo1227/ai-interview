# AI 面试系统多租户 SaaS 改造设计

## 1. 背景

当前系统是一套应用连接一个 PostgreSQL 数据库，`backend/app/config/database.py` 在进程启动时创建全局 `SessionLocal`。所有登录用户、职位、简历、面试、Offer、笔试、工作流和系统配置都默认属于同一个组织，多处后台任务也会直接创建全局数据库会话。

系统未来需要持续接入更多公司。如果每增加一家公司都部署一套后端和数据库，运维成本会随客户数量线性增长，不符合 SaaS 的规模化目标。因此本次改造采用单应用、单数据库、共享表的多租户架构，通过 `tenant_id` 与 PostgreSQL Row Level Security（RLS）实现公司数据隔离。

## 2. 目标与非目标

### 2.1 目标

- 一套前端、一套后端和一个 PostgreSQL 数据库服务多个公司。
- 新增公司时只创建租户及其初始配置，不新增 Docker 服务或数据库。
- 用户账号只属于一家公司，不支持跨公司切换。
- 相同邮箱可在不同公司分别注册。
- 应用层和数据库层同时阻止跨租户读写。
- 后台任务、公开链接、上传文件、SMTP、LLM 和工作流全部按租户隔离。
- 将现有数据无损迁移到默认租户 `careray`。
- 保持现有业务功能和 API 行为，跨租户资源统一返回 404，避免泄露资源是否存在。

### 2.2 非目标

- 本阶段不实现计费、套餐、配额和在线支付。
- 本阶段不支持一个用户加入多家公司。
- 本阶段不为每家公司创建独立数据库或 Schema。
- 本阶段不引入微服务或外部任务队列；现有后台任务先完成租户化。
- 本阶段不实现客户自助绑定任意公网域名，域名由平台管理员维护。

## 3. 核心架构决策

采用“共享数据库、共享表、每行包含 `tenant_id`”的模式。

```text
浏览器
  │ 公司代码 / 访问域名
  ▼
统一前端
  │ 登录请求
  ▼
统一后端 ── 解析租户 ── 验证用户属于该租户
  │ JWT: user_id + tenant_id + role
  ▼
租户数据库会话 ── SET LOCAL app.current_tenant_id
  ▼
PostgreSQL RLS ── 仅允许访问当前 tenant_id 的记录
```

公司选择只负责确定租户，不能携带数据库地址或决定数据库连接。登录成功后，后端只信任签名 JWT 中的 `tenant_id`，普通业务接口不接受客户端自行传入的租户 ID。

## 4. 租户与平台数据模型

### 4.1 全局表

新增以下不属于具体租户的全局表：

#### `tenants`

| 字段 | 说明 |
| --- | --- |
| `id` | UUID 主键 |
| `code` | 唯一公司代码，例如 `careray` |
| `name` | 公司显示名称 |
| `status` | `active`、`disabled` |
| `logo_url` | 可选品牌 Logo |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

`code` 仅允许小写字母、数字和短横线，创建后不可修改，避免登录链接失效。

#### `tenant_domains`

| 字段 | 说明 |
| --- | --- |
| `id` | UUID 主键 |
| `tenant_id` | 所属租户 |
| `domain` | 唯一域名，例如 `interview.careray.com` |
| `is_primary` | 是否为主域名 |
| `created_at` | 创建时间 |

域名统一转为小写并移除端口后匹配。请求中的 `Host` 必须来自可信代理传递的原始域名。

#### `platform_users`

平台管理员与公司用户分离。平台管理员只能通过独立的 `/api/platform/*` 接口创建、停用和查看租户，不直接参与任何公司的招聘业务。

#### `public_access_tokens`

统一管理公开访问凭证，替代业务表直接依赖裸 token 的做法：

| 字段 | 说明 |
| --- | --- |
| `token_hash` | 令牌哈希，不保存明文 |
| `tenant_id` | 所属租户 |
| `resource_type` | `offer`、`coding_test`、`department_review` 等 |
| `resource_id` | 目标资源 ID |
| `expires_at` | 过期时间 |
| `revoked_at` | 撤销时间 |

公开接口先通过令牌定位租户，再建立该租户的数据库上下文，最后读取资源。响应不得暴露其他租户信息。

### 4.2 租户业务表

以下现有表增加非空 `tenant_id UUID`：

- `users`
- `positions`
- `question_banks`
- `resumes`
- `department_reviews`
- `interviews`
- `interview_panels`
- `offers`
- `offer_templates`
- `coding_tests`
- `coding_submissions`
- `system_configs`
- `workflows`
- `workflow_nodes`
- `workflow_edges`
- `workflow_executions`
- `workflow_node_executions`

所有新建记录的 `tenant_id` 必须由后端租户上下文写入，禁止由普通 API 请求体赋值。

### 4.3 唯一约束与关系约束

- `users.email` 的全局唯一约束改为 `UNIQUE (tenant_id, email)`。
- `system_configs.singleton_key` 改为 `UNIQUE (tenant_id)`，每家公司恰好一条系统配置。
- Offer、笔试等公开 token 在迁移至 `public_access_tokens` 前继续保持全局唯一。
- 业务常用唯一字段必须把 `tenant_id` 作为约束前缀。
- 每个父表增加 `UNIQUE (tenant_id, id)`。
- 关键关系使用复合外键，例如 `(tenant_id, position_id)` 引用 `positions(tenant_id, id)`，从数据库层阻止跨租户关联。

### 4.4 索引

所有高频查询索引以 `tenant_id` 开头，例如：

- `(tenant_id, email)`
- `(tenant_id, status)`
- `(tenant_id, position_id)`
- `(tenant_id, created_at)`
- `(tenant_id, candidate_email)`

迁移后使用真实数据量检查查询计划，避免只添加单列 `tenant_id` 索引而无法覆盖业务过滤条件。

## 5. 登录与租户识别

### 5.1 登录页

登录页加载启用的租户列表，只返回 `code`、`name`、`logo_url` 和主域名，不返回数据库或内部配置。用户选择公司后提交：

```json
{
  "tenant_code": "careray",
  "email": "admin@example.com",
  "password": "********"
}
```

如果通过公司专属域名访问，前端自动预选对应公司。提交的 `tenant_code` 必须与域名映射一致；在统一入口域名访问时允许用户选择公司。

### 5.2 登录验证

登录接口执行顺序：

1. 根据 `tenant_code` 或请求域名读取启用租户。
2. 建立该租户的数据库上下文。
3. 使用 `(tenant_id, email)` 查询用户。
4. 校验密码、用户状态和租户状态。
5. 签发 JWT。

JWT 至少包含：

```json
{
  "sub": "用户 UUID",
  "tenant_id": "租户 UUID",
  "role": "admin",
  "exp": 0
}
```

`sub` 改为用户 UUID，不能继续只使用邮箱，因为不同租户允许存在相同邮箱。

### 5.3 已认证请求

每个已认证请求执行：

1. 验证 JWT 签名和过期时间。
2. 读取 `tenant_id` 与用户 ID。
3. 验证租户仍启用。
4. 建立租户数据库会话并设置 RLS 上下文。
5. 在该上下文中读取用户与业务数据。
6. 如果使用公司专属域名，再验证域名租户与 JWT 租户一致。

客户端传入的 `tenant_id`、公司请求头或查询参数不得覆盖 JWT 中的租户。

## 6. 数据库会话与 RLS

### 6.1 数据库角色

至少拆分两个数据库角色：

- `app_runtime`：应用运行账号，无 `BYPASSRLS`，不能修改 RLS 策略。
- `app_migration`：仅用于 Alembic、初始化和数据修复，不提供给 API 容器日常运行。

生产环境不能让 API 使用表所有者或超级用户连接，否则可能绕过 RLS。

### 6.2 租户会话

保留一个 SQLAlchemy Engine 和连接池，但不再允许业务代码直接调用裸 `SessionLocal()`。新增统一接口：

```text
tenant_session(tenant_id)
```

会话开启事务后执行等价语句：

```sql
SELECT set_config('app.current_tenant_id', :tenant_id, true);
```

第三个参数必须为 `true`，使设置仅在当前事务内有效。连接归还连接池后不得残留租户上下文。

### 6.3 RLS 策略

所有租户业务表启用并强制执行 RLS：

```sql
ALTER TABLE resumes ENABLE ROW LEVEL SECURITY;
ALTER TABLE resumes FORCE ROW LEVEL SECURITY;

CREATE POLICY resumes_tenant_isolation ON resumes
USING (
  tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
)
WITH CHECK (
  tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
);
```

其他业务表使用相同原则。未设置租户上下文时查询返回零行，写入被拒绝，不能默认访问全部数据。

## 7. API 与服务层改造

### 7.1 请求依赖

将当前 `get_db` 拆分为：

- `get_unscoped_db`：仅允许登录前的租户解析、平台管理和公开 token 定位使用。
- `get_tenant_context`：验证 JWT 或公开 token，生成可信租户上下文。
- `get_tenant_db`：基于可信租户上下文创建带 RLS 的 Session。

普通业务路由必须依赖 `get_tenant_db`，禁止使用 `get_unscoped_db`。

### 7.2 服务层

服务函数继续接收 `Session`，但所有新增对象通过公共工厂或会话上下文自动填充 `tenant_id`。读取单条资源时，跨租户 ID 与不存在 ID 都返回 404。

应用层仍保留显式的 `tenant_id` 过滤，以提高可读性、查询性能和测试确定性；RLS 是最后防线，不是替代业务查询条件。

### 7.3 后台任务

当前简历解析、AI 评估、面试分析、笔试评分和邮件任务中存在直接创建 `SessionLocal()` 的代码，必须全部改为显式传递：

```text
tenant_id + resource_id
```

后台任务启动后使用 `tenant_session(tenant_id)` 重新建立会话，不得传递请求 Session，也不得只凭资源 ID 推断租户。日志必须同时记录 `tenant_id`、任务类型和资源 ID。

## 8. 公开链接

Offer 确认、在线笔试和部门评审不依赖登录，但仍必须隔离租户：

1. 生成高熵随机 token。
2. 数据库只保存 token 哈希。
3. `public_access_tokens` 记录 token 对应的租户和资源。
4. 公开请求先校验 token、有效期和撤销状态。
5. 建立对应租户上下文后读取业务资源。
6. token 无效、过期、撤销或资源不存在统一返回 404/410，不暴露租户信息。

邮件中的链接优先使用该租户的主域名；没有专属域名时使用统一入口域名。

公开职位列表和职位详情没有一次性 token，必须通过请求域名或显式公司代码建立只读租户上下文。统一入口访问公开职位时，URL 使用公司代码，例如 `/public/careray/jobs/{position_id}`；公司专属域名访问时由域名映射租户。两种方式同时出现且结果不一致时拒绝请求。

## 9. 文件与音频隔离

现有 `/uploads` 通过 `StaticFiles` 整体公开，不能继续用于多租户生产环境。

文件存储路径改为：

```text
uploads/{tenant_id}/resumes/
uploads/{tenant_id}/question_banks/
uploads/{tenant_id}/audio/
uploads/{tenant_id}/full_audio/
```

数据库保存相对对象键，不保存可由客户端任意拼接的绝对路径。下载文件必须经过授权接口：

```text
GET /api/files/{file_id}
```

接口验证文件记录的 `tenant_id`、用户权限和资源归属后再返回内容。公开文件使用短期签名 token。所有路径在访问前执行规范化，并验证最终路径仍位于当前租户目录内，防止路径穿越。

## 10. 租户级配置

`system_configs` 从全局单例改为租户单例：

- LLM Provider、Base URL、API Key 和模型
- SMTP 主机、账号、授权码和安全连接类型
- 发件人和邮件启用状态
- 前端主域名
- 提示词配置

所有配置读取函数必须从当前租户会话读取。缓存键必须包含 `tenant_id`，不能继续使用进程级全局配置缓存。

敏感配置后续可迁移至密钥服务；本阶段至少确保 API 响应不返回明文密码和 API Key。

## 11. 平台管理与租户开通

平台管理员新增公司时执行一个事务化、可重试的开通流程：

1. 创建 `tenants` 记录。
2. 创建主域名记录。
3. 创建租户默认 `system_configs`。
4. 创建该公司的首个管理员用户。
5. 写入审计日志。

任何一步失败则整体回滚。重复提交相同公司代码时返回明确冲突，不创建半成品租户。

平台接口使用独立认证入口、独立数据库依赖和独立权限检查，不复用租户 JWT。租户管理员不能读取租户清单、修改域名映射或操作其他租户状态。

停用租户后：

- 禁止新登录。
- 已签发 token 在下一次请求时失效。
- 后台任务停止处理该租户的新任务。
- 数据保留，不自动删除。

## 12. 前端改造

- 登录表单增加公司选择，加载启用租户列表。
- 公司专属域名自动预选且锁定公司；统一入口允许选择。
- 登录请求携带 `tenant_code`。
- AuthContext 保存并解析当前租户信息。
- 页面顶部显示当前公司名称，避免操作人员混淆环境。
- 用户无跨公司成员关系，因此不提供登录后的公司切换器。
- 退出登录只清除当前会话，不影响其他浏览器或设备。
- 所有普通 API 请求不发送可修改的 `tenant_id`。

## 13. 数据迁移策略

现有全部数据归入默认租户 `careray`。迁移分阶段执行，避免一次性切换导致不可回滚。

### 阶段 A：兼容性迁移

1. 创建 `tenants`、`tenant_domains`、`platform_users` 和 `public_access_tokens`。
2. 创建 `careray` 默认租户。
3. 为业务表添加允许为空的 `tenant_id`。
4. 按外键拓扑顺序把现有记录回填为 `careray`。
5. 校验所有业务表无空租户、无孤儿关系、记录数一致。

### 阶段 B：约束与代码切换

1. 添加租户组合索引和复合关系约束。
2. 将 `tenant_id` 改为非空。
3. 部署支持租户登录、JWT 和租户 Session 的后端。
4. 部署带公司选择的前端。
5. 将全局系统配置改为 `careray` 的租户配置。
6. 改造后台任务、公开链接和文件访问。

### 阶段 C：启用 RLS

1. 在预发布环境用 `app_runtime` 角色执行全量测试。
2. 为每张租户业务表启用并强制 RLS。
3. 验证无租户上下文时不可读取或写入数据。
4. 在生产环境启用 RLS。
5. 创建第二个测试租户，完成跨租户攻击用例验证。

RLS 不应在应用尚未完成租户上下文改造前启用，否则现有接口会全部查不到数据。

## 14. 测试方案

### 14.1 单元测试

- 两个租户可以创建相同邮箱用户。
- 登录必须同时匹配公司和用户。
- JWT 包含正确 `tenant_id` 和用户 UUID。
- 普通请求不能用请求参数覆盖 JWT 租户。
- 新对象自动使用当前租户，客户端传入租户字段会被忽略或拒绝。

### 14.2 数据库集成测试

- 租户 A 只能看到租户 A 的数据。
- 使用租户 A 会话读取租户 B 已知 UUID 返回空。
- 使用租户 A 会话写入租户 B 的 `tenant_id` 被 RLS 拒绝。
- 未设置租户上下文时业务表返回零行且无法写入。
- 复合外键阻止把租户 A 的简历关联到租户 B 的职位。
- 连接池复用后不会残留上一个请求的租户上下文。

### 14.3 业务回归测试

- 职位、简历、面试、Offer、笔试、工作流、仪表盘全部按租户隔离。
- AI 和 SMTP 使用当前租户配置。
- 后台任务不会处理或更新其他租户资源。
- 公开链接只能访问 token 对应的租户资源。
- 文件下载和音频访问不能跨租户，也不能路径穿越。

### 14.4 端到端验收

准备 `careray` 和 `photonthix` 两个租户，使用相同管理员邮箱分别登录，创建同名职位和候选人，验证列表、统计、搜索、邮件、AI、附件和公开链接完全隔离。

## 15. 可观测性与审计

- 每个请求生成 `request_id`，日志固定包含 `tenant_id`、`user_id`、路由和状态码。
- 后台任务日志包含 `tenant_id`、任务 ID 和资源 ID。
- 平台管理员的租户创建、停用、域名修改操作写入审计日志。
- 监控按租户聚合请求量、错误率、后台任务失败和存储使用量。
- 日志不得记录密码、SMTP 授权码、LLM API Key、JWT 或公开 token 明文。

## 16. 部署与运维变化

改造完成后只保留一套生产应用：

```text
Caddy → frontend → backend → PostgreSQL
```

所有公司共用应用版本和数据库迁移。新增租户不触发部署。数据库备份仍为整库备份，同时提供按 `tenant_id` 导出工具用于客户数据交付和问题排查。

域名接入分为两类：

- 统一入口：用户在登录页选择公司，无需新增域名。
- 公司专属域名：平台管理员增加 DNS 和 `tenant_domains` 映射，Caddy 增加对应 HTTPS 站点；后续可再建设自动化域名接入。

## 17. 上线与回滚

上线前执行整库备份、上传目录备份和迁移演练，并记录各表迁移前后行数。

回滚原则：

- 在启用 RLS 前，可回滚到兼容旧接口的应用版本。
- 启用 RLS 后若应用异常，先使用迁移角色关闭策略或回滚策略迁移，再回滚应用；普通运行账号不得执行此操作。
- 不在回滚中删除 `tenant_id`、租户表或新索引，避免破坏已写入的新数据。
- 数据恢复只作为最后手段，恢复前先保留故障现场快照。

## 18. 实施顺序

1. 租户基础表与默认租户迁移。
2. 业务表 `tenant_id` 回填、索引和复合约束。
3. 租户上下文、登录和 JWT 改造。
4. 全部业务路由和服务层租户化。
5. 后台任务与配置读取租户化。
6. 公开链接改造。
7. 文件存储与下载鉴权改造。
8. 前端公司选择和公司标识。
9. PostgreSQL 运行角色拆分与 RLS。
10. 双租户端到端测试、迁移演练和生产发布。

## 19. 验收标准

- 新增公司无需新增 Docker、后端或数据库。
- 同邮箱可以分别登录不同公司。
- 任何普通接口、后台任务、公开链接和文件请求都无法跨租户访问。
- 数据库运行账号即使执行遗漏租户过滤的 SQL，也受 RLS 限制。
- 现有数据全部归属 `careray`，迁移前后记录数和业务结果一致。
- `careray` 与 `photonthix` 能在同一应用中独立配置管理员、SMTP、LLM、提示词和前端域名。
- 全量后端测试、前端构建和双租户端到端测试通过后才能上线。
