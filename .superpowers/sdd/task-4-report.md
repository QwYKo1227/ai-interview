# Task 4 实施报告：公司识别、租户内登录和 JWT

## 状态

已完成。实现基于基准提交 `3b8b0b61cf278927957edda6d321a093d13a7a10`，严格按 RED → GREEN 推进。

## RED 证据

### 第一轮：租户选择、登录与 JWT

命令：

```text
cd backend && pytest tests/test_tenant_auth.py -v
```

结果：新增的 11 项测试全部失败。失败准确暴露旧行为：

- 缺少 `GET /api/auth/tenants`；
- `/login` 忽略 `tenant_code`，同邮箱会跨租户命中错误用户；
- 不存在或禁用租户仍可能登录；
- 禁用用户返回差异化 403，其他错误使用英文文案；
- JWT 仍将 email 放入 `sub`，且不含固定 `tenant_id`/`role`；
- `/token` 不要求 `tenant_code`，可绕过公司选择。

### 第二轮：JWT/域名依赖

筛选运行 18 项，6 项按预期失败：有效 UUID-sub token 仍返回 401、专属域名匹配未生效、域名错配未返回 403、未知 Host 统一入口未生效、旧 email-sub token 仍被接受、`tenant_dependencies` 尚不存在。另为严格 decoder 增加专测并确认因函数缺失失败。

### 第三轮：认证模块自身的数据范围

`test_authenticated_user_management_is_tenant_scoped` 先失败，证明 `/api/auth/users` 在 JWT 已验证后仍使用旧 `get_db` 返回其他租户用户。

## GREEN 证据

- 第一轮定向：11 passed。
- 第二轮定向：19 passed。
- 最终认证套件：31 passed。
- 完整 backend：在认证模块租户化前曾运行到 225 passed；最终变更后的新鲜完整结果见下方验证记录。

测试过程中曾遇到 2 个夹具级错误：把租户会话临时绑定到测试 SQLite 的同一个 `SingletonThreadPool` Engine 后，TestClient 跨线程回收了仍在使用的连接。确认根因后移除该错误的测试绑定，恢复使用生产会话工厂与共享测试 URI；生产认证逻辑未因此降级。

## 实现摘要

- `GET /api/auth/tenants` 只返回 ACTIVE 租户的 `TenantSummary` 安全字段，并解析主域名。
- `POST /api/auth/login` 先通过未绑定的 tenant-capable 全局会话查 ACTIVE 租户，再通过 `tenant_session(tenant.id)` 按 `(tenant_id, email)` 查用户。
- 不存在/禁用公司、不存在/禁用用户、错误密码统一返回 401：`公司、账号或密码错误`。
- `/api/auth/token` 保留为 deprecated 兼容入口，但 `tenant_code` 是必填 Form 字段，并复用同一租户登录流程；不可绕过公司选择。
- JWT 固定为 `sub=<user UUID>`、`tenant_id=<tenant UUID>`、`role`、`exp`。decoder 严格校验签名、过期、必需 claim、claim 类型、UUID 和合法角色，不接受旧 email-sub token。
- `get_tenant_context` 仅从已验证 JWT 和数据库域名映射构造；忽略请求体、query、`X-Tenant-ID` 等不可信租户输入。
- Host 规范化大小写和端口；专属域名与 JWT tenant 不一致返回 403，未知 Host 视为统一入口。
- `get_tenant_db` 只从可信 `TenantContext` 创建 `TenantSession`，并在依赖退出时关闭。
- 认证模块内的用户管理和个人资料数据库依赖同步切换为 `get_tenant_db`，避免 JWT 验证后再次使用未绑定会话。

## 变更文件

- `backend/app/core/security.py`
- `backend/app/core/tenant_context.py`
- `backend/app/core/tenant_dependencies.py`（新增）
- `backend/app/routes/auth.py`
- `backend/app/routes/offers.py`
- `backend/app/routes/offer_templates.py`
- `backend/app/schemas/user.py`
- `backend/tests/conftest.py`
- `backend/tests/test_tenant_auth.py`（新增）
- `.superpowers/sdd/task-4-report.md`（本报告）

## 自审

- 租户列表响应断言精确字段集合，未泄露 status、邮件配置、数据库配置或其他内部数据。
- 登录查询顺序符合全局租户发现 → 租户绑定用户查询；同邮箱跨租户已覆盖。
- 认证错误无公司/账号枚举差异；新增代码未记录密码或 token。
- JWT 没有 email-sub fallback；缺失/非法 UUID、非法类型、过期和错误签名均已覆盖。
- 域名/JWT 403、Host 大小写/端口、未知 Host 和不可信 header/query 均已覆盖。
- `get_tenant_db` 的 scope 与 close 均由测试验证。
- Task 5 仍需按计划把其余业务路由的 legacy `get_db` 批量迁移；本任务只迁移了认证模块和直接导入认证依赖的兼容调用。

## 关注点

- 现有前端仍调用 `/auth/token` 且未提交 `tenant_code`，现在会得到 422。这是有意的安全性弃用策略；后续前端任务应切换到 JSON `/auth/login`，或在过渡期为 form 显式加入 `tenant_code`。
- 完整测试仍报告项目既有的 SQLAlchemy/Pydantic/PyPDF2/ffmpeg 等 warnings；本任务未扩大范围处理。

## 最终验证

提交前新鲜运行：

```text
cd backend && pytest
226 passed, 603 warnings in 79.61s
```

退出码为 0；warnings 为项目既有弃用和本地 ffmpeg 环境提示，无测试失败或错误。
