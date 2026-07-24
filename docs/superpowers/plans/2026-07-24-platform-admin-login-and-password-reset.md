# 平台管理员入口与企业管理员密码重置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在普通登录页增加平台管理员入口，并允许平台管理员安全地查看和重置指定公司的企业管理员密码，同时立即注销目标账号的旧会话。

**Architecture:** 平台控制面继续使用独立平台令牌，通过现有非租户会话验证操作者，再为目标公司显式绑定租户上下文。企业令牌增加凭据版本声明；密码变更与版本递增、审计日志写入在同一事务中完成。前端把企业管理员列表并入公司详情响应，并在详情抽屉内完成密码重置交互。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、PostgreSQL RLS、Pydantic、JWT、React 19、TypeScript、Ant Design、Vitest、Pytest。

## Global Constraints

- 所有新增用户界面、错误提示和设计文档使用中文。
- 平台身份继续使用独立 `platform_token`，不得接受企业令牌。
- 只允许修改角色为 `admin` 的企业账号。
- 新密码必须为 12–72 个 UTF-8 字节，并至少包含一个字母和一个数字。
- 任何响应、日志和审计记录都不得包含明文密码、确认密码或密码散列。
- 密码更新后该账号此前签发的企业令牌必须立即失效。
- 不增加新的生产依赖。

---

### Task 1: 凭据版本与企业令牌失效

**Files:**
- Create: `backend/alembic/versions/s8t9u0v1w2x3_add_user_credential_version.py`
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/core/security.py`
- Modify: `backend/app/core/tenant_dependencies.py`
- Modify: `backend/app/routes/auth.py`
- Test: `backend/tests/test_tenant_auth.py`
- Test: `backend/tests/test_tenant_migration_verifier.py`

**Interfaces:**
- Produces: `User.credential_version: int`，`AccessTokenClaims.credential_version: int`，以及带 `credential_version` 参数的 `create_access_token(...)`。
- Produces: 企业用户自行修改密码时递增凭据版本，并由 `get_current_user_dep` 拒绝旧版本令牌。

- [ ] **Step 1: 编写失败的模型、迁移与令牌测试**

```python
def test_access_token_carries_credential_version(tenant_a):
    token = create_access_token(
        user_id=uuid4(), tenant_id=tenant_a.id, role="admin", credential_version=3
    )
    assert decode_access_token(token).credential_version == 3

def test_old_credential_version_is_rejected(client, test_admin, admin_headers):
    test_admin.credential_version += 1
    db.commit()
    assert client.get("/api/auth/me", headers=admin_headers).status_code == 401
```

迁移测试断言升级后 `users.credential_version` 为 `INTEGER NOT NULL DEFAULT 1`，降级后该列不存在。

- [ ] **Step 2: 运行定向测试并确认失败**

Run: `cd backend; pytest tests/test_tenant_auth.py tests/test_tenant_migration_verifier.py -q`

Expected: FAIL，原因是模型、迁移和 JWT 声明尚不存在。

- [ ] **Step 3: 实现数据库列和 JWT 版本检查**

```python
credential_version = Column(Integer, nullable=False, default=1, server_default="1")

@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    tenant_id: UUID
    role: str
    credential_version: int
```

`create_access_token` 写入整数声明，`decode_access_token` 严格校验其为大于零的整数。所有签发点传入 `user.credential_version`；`get_current_user_dep` 在读取用户后比较版本，不一致时返回 401。`change_password` 更新密码散列时执行 `current_user.credential_version += 1`。

Alembic 升级使用：

```python
op.add_column(
    "users",
    sa.Column("credential_version", sa.Integer(), server_default="1", nullable=False),
)
```

降级使用 `op.drop_column("users", "credential_version")`，迁移的 `down_revision` 指向 `r7s8t9u0v1w2`。

- [ ] **Step 4: 更新所有测试令牌工厂并运行测试**

Run: `cd backend; pytest tests/test_tenant_auth.py tests/test_tenant_migration_verifier.py tests/test_tenant_route_isolation.py tests/test_tenant_onboarding.py -q`

Expected: PASS。

- [ ] **Step 5: 提交凭据版本功能**

```bash
git add backend/alembic/versions/s8t9u0v1w2x3_add_user_credential_version.py backend/app/models/models.py backend/app/core/security.py backend/app/core/tenant_dependencies.py backend/app/routes/auth.py backend/tests
git commit -m "feat: invalidate tenant sessions after password change"
```

### Task 2: 平台端企业管理员查询、重置与审计

**Files:**
- Modify: `backend/app/schemas/tenant.py`
- Modify: `backend/app/services/tenant_service.py`
- Modify: `backend/app/routes/platform.py`
- Test: `backend/tests/test_tenant_onboarding.py`
- Test: `backend/tests/integration/test_postgres_rls.py`

**Interfaces:**
- Consumes: `User.credential_version` 和 `get_password_hash`。
- Produces: `TenantAdminResponse`、`TenantAdminPasswordResetRequest`、公司详情的 `admins` 字段。
- Produces: `reset_tenant_admin_password(db, *, tenant_id, user_id, new_password, actor_id) -> None`。
- Produces: `PATCH /api/platform/tenants/{tenant_id}/admins/{user_id}/password`。

- [ ] **Step 1: 编写平台 API 失败测试**

覆盖以下断言：公司详情只返回 `admin` 账号；弱密码和额外字段返回 422；非管理员目标和其他公司的目标返回 404；成功后旧密码登录失败、新密码登录成功；旧令牌访问 `/api/auth/me` 返回 401；审计操作为 `tenant.admin_password_reset` 且详情不含任何密码字段。

```python
response = platform_client.patch(
    f"/api/platform/tenants/{tenant.id}/admins/{admin.id}/password",
    headers=platform_headers,
    json={"new_password": "Replacement123"},
)
assert response.status_code == 200
assert response.json() == {"success": True}
```

- [ ] **Step 2: 运行平台定向测试并确认失败**

Run: `cd backend; pytest tests/test_tenant_onboarding.py -q`

Expected: FAIL，原因是响应字段和重置路由尚不存在。

- [ ] **Step 3: 增加严格请求/响应模型与密码校验**

```python
class TenantAdminPasswordResetRequest(BaseModel):
    new_password: str
    model_config = ConfigDict(extra="forbid")

class TenantAdminResponse(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str | None
    is_active: bool
    model_config = ConfigDict(from_attributes=True)
```

提取共享的密码强度校验函数，按 UTF-8 字节数校验 12–72，并校验字母和数字；企业开户、用户自行改密和平台重置复用相同规则。

- [ ] **Step 4: 实现租户绑定、事务重置和审计**

服务函数在 `with db.begin()` 内依次验证平台操作者和公司，调用 `set_tenant_context(db, tenant_id)`，按 `tenant_id`、`user_id`、`UserRole.ADMIN` 查询目标用户，然后更新：

```python
target.hashed_password = get_password_hash(new_password)
target.credential_version += 1
db.add(PlatformAuditLog(
    actor_id=actor_id,
    action="tenant.admin_password_reset",
    target_tenant_id=tenant_id,
    details={
        "target_user_id": str(target.id),
        "target_email": target.email,
        "credential_version": target.credential_version,
    },
))
```

`finally` 中释放临时租户上下文。公司详情读取管理员时采用相同租户绑定，并在返回前分离响应数据，避免会话释放后懒加载。

- [ ] **Step 5: 运行单元及 PostgreSQL RLS 集成测试**

Run: `cd backend; pytest tests/test_tenant_onboarding.py tests/integration/test_postgres_rls.py -q`

Expected: PASS；跨租户测试确认无法修改其他公司的用户。

- [ ] **Step 6: 提交平台密码重置后端**

```bash
git add backend/app/schemas/tenant.py backend/app/services/tenant_service.py backend/app/routes/platform.py backend/tests
git commit -m "feat: let platform admins reset tenant admin passwords"
```

### Task 3: 普通登录页平台入口

**Files:**
- Modify: `frontend/src/pages/Login/index.tsx`
- Modify: `frontend/src/pages/Login/Login.test.tsx`

**Interfaces:**
- Produces: 登录页上的“平台管理员入口”，通过 React Router 导航到 `/platform/login`。

- [ ] **Step 1: 编写失败的入口测试**

```tsx
it('navigates to the platform login', async () => {
  mockGet.mockResolvedValueOnce([]);
  const user = userEvent.setup();
  renderLogin();
  await user.click(await screen.findByRole('link', { name: '平台管理员入口' }));
  expect(screen.getByText('用于公司开通、域名与企业管理员管理')).toBeInTheDocument();
  expect(window.location.pathname).toBe('/platform/login');
});
```

测试渲染器使用带 `/login` 和 `/platform/login` 路由的 `MemoryRouter`，通过路由内容断言跳转结果，避免读取浏览器全局地址。

- [ ] **Step 2: 运行登录页测试并确认失败**

Run: `cd frontend; npm test -- src/pages/Login/Login.test.tsx`

Expected: FAIL，原因是入口链接尚不存在。

- [ ] **Step 3: 实现入口及说明**

在登录按钮下方增加语义化链接：

```tsx
<div className="login-platform-entry">
  <Link to="/platform/login">平台管理员入口</Link>
  <span>用于公司开通、域名与企业管理员管理</span>
</div>
```

复用现有登录卡片样式，保证键盘焦点可见，移动端不溢出。

- [ ] **Step 4: 运行登录页测试并提交**

Run: `cd frontend; npm test -- src/pages/Login/Login.test.tsx`

Expected: PASS。

```bash
git add frontend/src/pages/Login/index.tsx frontend/src/pages/Login/Login.test.tsx
git commit -m "feat: add platform admin entry to login"
```

### Task 4: 公司详情企业管理员重置界面

**Files:**
- Modify: `frontend/src/types/platform.ts`
- Modify: `frontend/src/pages/Platform/TenantDetailDrawer.tsx`
- Modify: `frontend/src/pages/Platform/TenantDetailDrawer.test.tsx`
- Modify: `frontend/src/pages/Platform/platform.css`

**Interfaces:**
- Consumes: 公司详情 `admins: PlatformTenantAdmin[]`。
- Consumes: `PATCH /platform/tenants/{tenantId}/admins/{userId}/password`，请求 `{ new_password: string }`。

- [ ] **Step 1: 编写失败的管理员列表和重置测试**

测试数据给公司详情增加一个管理员，断言邮箱、状态和“重置密码”按钮可见；点击后填写两次密码并提交，断言：

```tsx
expect(mockPatch).toHaveBeenCalledWith(
  '/platform/tenants/tenant-careray/admins/admin-1/password',
  { new_password: 'Replacement123' },
);
```

另测两次密码不一致时不发请求、接口失败时弹窗保持打开并显示中文错误、切换公司时关闭并清空重置弹窗。

- [ ] **Step 2: 运行详情抽屉测试并确认失败**

Run: `cd frontend; npm test -- src/pages/Platform/TenantDetailDrawer.test.tsx`

Expected: FAIL，原因是管理员类型和界面尚不存在。

- [ ] **Step 3: 增加类型和重置交互**

```ts
export interface PlatformTenantAdmin {
  id: string;
  email: string;
  full_name?: string | null;
  is_active: boolean;
}

export interface PlatformTenantDetail extends PlatformTenant {
  domains: PlatformDomain[];
  admins: PlatformTenantAdmin[];
}
```

在公司摘要与域名区域之间加入企业管理员列表。重置弹窗使用两个密码输入框，前端校验 UTF-8 字节长度、字母、数字和二次输入一致；请求成功后关闭弹窗并显示成功消息，请求失败时显示中文错误且不清空输入。

- [ ] **Step 4: 完善布局并运行前端定向测试**

Run: `cd frontend; npm test -- src/pages/Platform/TenantDetailDrawer.test.tsx src/pages/Platform/Tenants.test.tsx src/pages/Login/Login.test.tsx`

Expected: PASS。

- [ ] **Step 5: 提交平台前端**

```bash
git add frontend/src/types/platform.ts frontend/src/pages/Platform/TenantDetailDrawer.tsx frontend/src/pages/Platform/TenantDetailDrawer.test.tsx frontend/src/pages/Platform/platform.css
git commit -m "feat: add tenant admin password reset UI"
```

### Task 5: 全量验证与本地部署

**Files:**
- Modify only if verification exposes a defect in files already listed above.

**Interfaces:**
- Consumes: Tasks 1–4 的完整实现。
- Produces: 可迁移、可构建、可在本地 HTTPS 环境验证的交付版本。

- [ ] **Step 1: 运行后端全量测试**

Run: `cd backend; pytest -q`

Expected: 全部测试通过；允许现有环境条件导致的明确 skip，不允许新增失败。

- [ ] **Step 2: 运行前端全量测试和生产构建**

Run: `cd frontend; npm test`

Expected: 全部测试通过。

Run: `cd frontend; npm run build`

Expected: TypeScript 与 Vite 构建成功。

- [ ] **Step 3: 检查迁移链和变更质量**

Run: `cd backend; alembic heads`

Expected: 仅有 `s8t9u0v1w2x3 (head)`。

Run: `git diff --check; git status --short`

Expected: 无空白错误；仅保留计划内文件变更。

- [ ] **Step 4: 重建本地服务并执行冒烟测试**

Run: `docker compose up -d --build backend frontend caddy`

Expected: 后端、前端和 Caddy 容器启动，数据库迁移成功且数据库未被重建。

Run: `curl.exe -k -I https://interview-local.careray.com/login; curl.exe -k -I https://interview-local.careray.com/platform/login`

Expected: 两个地址均返回 HTTP 200。

- [ ] **Step 5: 最终提交**

若验证修复产生新改动：

```bash
git add backend frontend
git commit -m "fix: complete platform admin password reset verification"
```

最终确认 `git status --short` 为空。
