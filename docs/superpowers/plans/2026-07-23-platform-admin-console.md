# 平台管理员控制台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有前端中增加与公司业务后台严格隔离的平台管理员控制台，通过页面完成公司开通、状态管理和域名维护。

**Architecture:** 平台控制台与公司后台共用构建产物和 Ant Design 依赖，但使用独立路由树、`platform_token`、Axios 客户端和认证上下文。所有写操作调用现有 `/api/platform/*` 接口，继续由后端事务、权限检查和审计日志保证一致性。

**Tech Stack:** React 19、TypeScript 5.9、React Router 7、Ant Design 6、Axios、Vitest、Testing Library、Vite、Docker Compose。

## Global Constraints

- 所有新增界面文案、错误提示和设计文档使用中文。
- 平台令牌只存储在 `localStorage.platform_token`，公司令牌继续只使用 `localStorage.token`。
- 平台请求不得携带公司令牌，公司请求不得携带平台令牌。
- 不增加平台管理员注册、公司删除、DNS/Hosts/Caddy 自动修改、计费或配额功能。
- 新建公司表单字段固定为 `code`、`name`、`primary_domain`、`admin_email`、`admin_password`。
- 初始管理员密码长度为 12 至 72 字节，且至少包含一个字母和一个数字。
- 主域名不能直接删除；停用公司、删除非主域名必须二次确认。
- 遵循测试先行：每项生产代码都必须先有能按预期失败的测试。

---

## 文件结构

- 新建 `frontend/src/types/platform.ts`：平台登录、公司、域名和表单类型。
- 新建 `frontend/src/utils/platformRequest.ts`：独立平台 API 客户端及令牌失效处理。
- 新建 `frontend/src/utils/platformRequest.test.ts`：平台令牌隔离回归测试。
- 新建 `frontend/src/contexts/PlatformAuthContext.tsx`：平台会话状态。
- 新建 `frontend/src/contexts/PlatformAuthContext.test.tsx`：平台登录、退出和并发状态测试。
- 新建 `frontend/src/components/Platform/PlatformProtectedRoute.tsx`：平台受保护路由。
- 新建 `frontend/src/components/Platform/PlatformProtectedRoute.test.tsx`：平台路由保护测试。
- 新建 `frontend/src/components/Platform/PlatformLayout.tsx`：平台顶部栏和内容布局。
- 新建 `frontend/src/pages/Platform/Login.tsx`：平台登录页。
- 新建 `frontend/src/pages/Platform/Login.test.tsx`：平台登录交互测试。
- 新建 `frontend/src/pages/Platform/Tenants.tsx`：公司概览、列表和开通弹窗。
- 新建 `frontend/src/pages/Platform/Tenants.test.tsx`：公司列表、开通和状态测试。
- 新建 `frontend/src/pages/Platform/TenantDetailDrawer.tsx`：详情及域名维护。
- 新建 `frontend/src/pages/Platform/TenantDetailDrawer.test.tsx`：域名操作测试。
- 新建 `frontend/src/pages/Platform/platform.css`：平台控制台局部样式和响应式规则。
- 修改 `frontend/src/router/index.tsx`：注册独立平台路由树。
- 修改 `frontend/src/main.tsx`：挂载 `PlatformAuthProvider`。

---

### Task 1: 平台 API 客户端与独立会话

**Files:**
- Create: `frontend/src/types/platform.ts`
- Create: `frontend/src/utils/platformRequest.ts`
- Create: `frontend/src/utils/platformRequest.test.ts`
- Create: `frontend/src/contexts/PlatformAuthContext.tsx`
- Create: `frontend/src/contexts/PlatformAuthContext.test.tsx`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Produces: `platformRequest`，以 `/api` 为 base URL，只读取 `platform_token`。
- Produces: `PlatformAuthProvider` 和 `usePlatformAuth()`，返回 `{ isAuthenticated, login(token), logout() }`。
- Produces: `PlatformTenant`、`PlatformTenantDetail`、`PlatformDomain`、`TenantOnboardingPayload` 类型。

- [ ] **Step 1: 编写平台请求隔离失败测试**

在 `frontend/src/utils/platformRequest.test.ts` 写入测试，分别验证平台请求只发送平台令牌、平台登录不发送令牌、401 只清理当前失败请求对应的平台令牌：

```ts
// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import platformRequest from './platformRequest';

describe('platformRequest', () => {
  const originalAdapter = platformRequest.defaults.adapter;

  afterEach(() => {
    platformRequest.defaults.adapter = originalAdapter;
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('sends only the platform token to protected platform endpoints', async () => {
    localStorage.setItem('token', 'tenant-token');
    localStorage.setItem('platform_token', 'platform-token');
    let authorization: string | undefined;
    platformRequest.defaults.adapter = async (config: any) => {
      authorization = config.headers.get('Authorization');
      return { data: [], status: 200, statusText: 'OK', headers: {}, config };
    };
    await platformRequest.get('/platform/tenants');
    expect(authorization).toBe('Bearer platform-token');
  });

  it('does not send a token to platform login', async () => {
    localStorage.setItem('platform_token', 'stale-token');
    let authorization: string | undefined;
    platformRequest.defaults.adapter = async (config: any) => {
      authorization = config.headers.get('Authorization');
      return { data: { access_token: 'new-token' }, status: 200, statusText: 'OK', headers: {}, config };
    };
    await platformRequest.post('/platform/auth/login', { email: 'admin@example.com', password: 'Password1234' });
    expect(authorization).toBeUndefined();
  });

  it('clears only the matching platform token after a 401', async () => {
    localStorage.setItem('token', 'tenant-token');
    localStorage.setItem('platform_token', 'old-platform-token');
    platformRequest.defaults.adapter = (config: any) => Promise.reject({
      config,
      response: { status: 401, data: {} },
    });
    await expect(platformRequest.get('/platform/tenants')).rejects.toBeTruthy();
    expect(localStorage.getItem('platform_token')).toBeNull();
    expect(localStorage.getItem('token')).toBe('tenant-token');
  });
});
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `cd frontend && npm test -- src/utils/platformRequest.test.ts`

Expected: FAIL，提示无法解析 `./platformRequest`。

- [ ] **Step 3: 实现平台类型和请求客户端**

在 `frontend/src/types/platform.ts` 定义：

```ts
export type TenantStatus = 'active' | 'inactive';

export interface PlatformDomain {
  id: string;
  domain: string;
  is_primary: boolean;
  created_at: string;
}

export interface PlatformTenant {
  id: string;
  code: string;
  name: string;
  logo_url?: string | null;
  primary_domain?: string | null;
  status: TenantStatus;
  created_at: string;
  updated_at: string;
}

export interface PlatformTenantDetail extends PlatformTenant {
  domains: PlatformDomain[];
}

export interface PlatformLoginPayload { email: string; password: string }

export interface TenantOnboardingPayload {
  code: string;
  name: string;
  primary_domain: string;
  admin_email: string;
  admin_password: string;
}
```

在 `frontend/src/utils/platformRequest.ts` 创建独立 Axios 实例；匿名端点固定为 `/platform/auth/login`，请求拦截器只读取 `platform_token`，响应拦截器使用失败请求头中的 Bearer token 与当前 token 比较后再清理并跳转 `/platform/login`。

- [ ] **Step 4: 运行平台请求测试并确认通过**

Run: `cd frontend && npm test -- src/utils/platformRequest.test.ts`

Expected: 3 tests passed。

- [ ] **Step 5: 编写平台认证上下文失败测试**

测试 `login('platform-token')` 写入独立存储、`logout()` 只删除平台令牌、初始状态由平台令牌决定，且普通 `token` 不会使平台会话变为已登录。

- [ ] **Step 6: 实现并挂载平台认证上下文**

`PlatformAuthContext.tsx` 使用 React state 保存当前平台 token 是否存在：

```ts
interface PlatformAuthContextValue {
  isAuthenticated: boolean;
  login: (token: string) => void;
  logout: () => void;
}
```

在 `frontend/src/main.tsx` 中把 `RouterProvider` 包在 `AuthProvider` 和 `PlatformAuthProvider` 内，两个 Provider 不互相调用。

- [ ] **Step 7: 运行上下文与请求相关测试**

Run: `cd frontend && npm test -- src/utils/platformRequest.test.ts src/contexts/PlatformAuthContext.test.tsx src/utils/request.test.ts src/contexts/AuthContext.test.tsx`

Expected: 全部通过，公司会话既有测试无回归。

- [ ] **Step 8: 提交会话隔离增量**

```bash
git add frontend/src/types/platform.ts frontend/src/utils/platformRequest.ts frontend/src/utils/platformRequest.test.ts frontend/src/contexts/PlatformAuthContext.tsx frontend/src/contexts/PlatformAuthContext.test.tsx frontend/src/main.tsx
git commit -m "feat: isolate platform administrator session"
```

---

### Task 2: 平台登录、保护路由和布局

**Files:**
- Create: `frontend/src/components/Platform/PlatformProtectedRoute.tsx`
- Create: `frontend/src/components/Platform/PlatformProtectedRoute.test.tsx`
- Create: `frontend/src/components/Platform/PlatformLayout.tsx`
- Create: `frontend/src/pages/Platform/Login.tsx`
- Create: `frontend/src/pages/Platform/Login.test.tsx`
- Create: `frontend/src/pages/Platform/platform.css`
- Modify: `frontend/src/router/index.tsx`

**Interfaces:**
- Consumes: `usePlatformAuth()` 和 `platformRequest`。
- Produces: `/platform/login` 匿名入口和 `/platform/tenants` 受保护入口。
- Produces: 平台专用布局的 `<Outlet />` 容器。

- [ ] **Step 1: 编写登录页失败测试**

测试邮箱、密码提交到 `/platform/auth/login`，成功后调用 `login(access_token)` 并导航 `/platform/tenants`；失败时显示统一中文提示。

```ts
expect(mockPost).toHaveBeenCalledWith('/platform/auth/login', {
  email: 'platform@example.com',
  password: 'Password1234',
});
expect(mockPlatformLogin).toHaveBeenCalledWith('platform-token');
expect(mockNavigate).toHaveBeenCalledWith('/platform/tenants', { replace: true });
```

- [ ] **Step 2: 运行登录测试并确认失败**

Run: `cd frontend && npm test -- src/pages/Platform/Login.test.tsx`

Expected: FAIL，提示 `Login.tsx` 不存在。

- [ ] **Step 3: 实现平台登录页**

使用 Ant Design `Form`、`Input`、`Button`、`Alert`，页面标题固定为“AI Interview 平台管理中心”。捕获请求失败后只显示“登录失败，请检查邮箱和密码”。已登录访问该页时直接导航 `/platform/tenants`。

- [ ] **Step 4: 编写并运行保护路由失败测试**

为未登录状态断言 `<Navigate to="/platform/login" replace />`，已登录状态渲染子组件。运行测试确认组件不存在导致失败。

- [ ] **Step 5: 实现保护路由和平台布局**

`PlatformProtectedRoute` 只读取 `usePlatformAuth()`。`PlatformLayout` 提供品牌、当前模块名称和退出按钮，退出后导航 `/platform/login`。平台布局不渲染公司业务菜单、公司名称或公司用户头像。

- [ ] **Step 6: 注册平台路由**

在 `router/index.tsx` 中增加：

```tsx
{
  path: '/platform/login',
  element: <PlatformLogin />,
},
{
  path: '/platform',
  element: <PlatformProtectedRoute><PlatformLayout /></PlatformProtectedRoute>,
  children: [
    { index: true, element: <Navigate to="/platform/tenants" replace /> },
    { path: 'tenants', element: <PlatformTenants /> },
  ],
},
```

此步骤可暂时为 `PlatformTenants` 使用只显示“公司管理”的最小组件，Task 3 再补齐功能。

- [ ] **Step 7: 运行登录、路由和公司登录回归测试**

Run: `cd frontend && npm test -- src/pages/Platform/Login.test.tsx src/components/Platform/PlatformProtectedRoute.test.tsx src/pages/Login/Login.test.tsx`

Expected: 全部通过。

- [ ] **Step 8: 提交平台入口增量**

```bash
git add frontend/src/components/Platform frontend/src/pages/Platform/Login.tsx frontend/src/pages/Platform/Login.test.tsx frontend/src/pages/Platform/platform.css frontend/src/router/index.tsx
git commit -m "feat: add platform administrator login"
```

---

### Task 3: 公司列表、统计与新建公司

**Files:**
- Create: `frontend/src/pages/Platform/Tenants.tsx`
- Create: `frontend/src/pages/Platform/Tenants.test.tsx`
- Modify: `frontend/src/pages/Platform/platform.css`

**Interfaces:**
- Consumes: `platformRequest.get('/platform/tenants')`。
- Consumes: `platformRequest.post('/platform/tenants', TenantOnboardingPayload)`。
- Produces: 公司统计卡片、公司表格、新建公司弹窗和 `onOpenTenant(tenantId)` 详情入口。

- [ ] **Step 1: 编写公司列表失败测试**

模拟 active 与 inactive 两家公司，断言总数、启用数、停用数、名称、代码、主域名和中文状态全部呈现；网络失败时出现“重新加载”操作。

- [ ] **Step 2: 运行列表测试并确认失败**

Run: `cd frontend && npm test -- src/pages/Platform/Tenants.test.tsx`

Expected: FAIL，因为页面尚未实现列表行为。

- [ ] **Step 3: 实现列表加载和统计**

使用 `useCallback` 的 `loadTenants()` 管理 loading/error/data。统计值通过数组计算，不增加后端接口。表格固定按公司代码展示后端返回顺序，状态使用 `Tag`。

- [ ] **Step 4: 编写新建公司失败测试**

打开“新建公司”，填写五个字段，断言调用：

```ts
expect(mockPost).toHaveBeenCalledWith('/platform/tenants', {
  code: 'photonthix',
  name: 'Photonthix',
  primary_domain: 'interview.photonthix.com',
  admin_email: 'admin@photonthix.com',
  admin_password: 'Password1234',
});
```

同时测试少于 12 位、缺少字母、缺少数字不会提交。

- [ ] **Step 5: 运行新建公司测试并确认失败**

Run: `cd frontend && npm test -- src/pages/Platform/Tenants.test.tsx`

Expected: 列表测试通过，新建公司测试因按钮或表单缺失而失败。

- [ ] **Step 6: 实现新建公司弹窗**

使用 Ant Design `Modal` 和 `Form`。公司代码在输入时转小写并校验 `^[a-z0-9-]+$`；域名和邮箱去除首尾空格并转小写；成功后 `form.resetFields()`、关闭弹窗并 `await loadTenants()`。409 显示“公司代码或域名已存在”，其他错误显示“公司创建失败，请稍后重试”。

- [ ] **Step 7: 运行公司页面测试**

Run: `cd frontend && npm test -- src/pages/Platform/Tenants.test.tsx`

Expected: 全部通过。

- [ ] **Step 8: 提交公司开通增量**

```bash
git add frontend/src/pages/Platform/Tenants.tsx frontend/src/pages/Platform/Tenants.test.tsx frontend/src/pages/Platform/platform.css
git commit -m "feat: add platform tenant onboarding"
```

---

### Task 4: 公司状态和域名维护

**Files:**
- Create: `frontend/src/pages/Platform/TenantDetailDrawer.tsx`
- Create: `frontend/src/pages/Platform/TenantDetailDrawer.test.tsx`
- Modify: `frontend/src/pages/Platform/Tenants.tsx`
- Modify: `frontend/src/pages/Platform/Tenants.test.tsx`
- Modify: `frontend/src/pages/Platform/platform.css`

**Interfaces:**
- Consumes: `GET /platform/tenants/{tenantId}`。
- Consumes: `PATCH /platform/tenants/{tenantId}/status`，body 为 `{ status: 'active' | 'inactive' }`。
- Consumes: `POST /platform/tenants/{tenantId}/domains`，body 为 `{ domain, is_primary }`。
- Consumes: `PATCH /platform/tenants/{tenantId}/domains/{domainId}`。
- Consumes: `DELETE /platform/tenants/{tenantId}/domains/{domainId}`。
- Produces: `TenantDetailDrawer({ tenantId, open, onClose, onChanged })`。

- [ ] **Step 1: 编写详情与主域名保护失败测试**

加载详情后断言所有域名显示；主域名显示“主域名”标记且没有删除按钮；非主域名显示“删除”按钮；页面显示 DNS/Hosts/Caddy 需另行维护的提示。

- [ ] **Step 2: 运行详情测试并确认失败**

Run: `cd frontend && npm test -- src/pages/Platform/TenantDetailDrawer.test.tsx`

Expected: FAIL，提示组件不存在。

- [ ] **Step 3: 实现只读详情抽屉**

抽屉打开且 `tenantId` 非空时请求详情。关闭或 tenantId 变化时忽略旧请求结果。错误状态提供“重新加载”。使用 `Descriptions` 展示基础信息，使用 `List` 展示域名。

- [ ] **Step 4: 编写域名新增、修改、设为主域名和删除失败测试**

分别断言调用正确 URL 与 payload。删除操作必须先点击确认；取消确认不得调用 DELETE。修改为主域名后重新加载详情并调用 `onChanged()`。

- [ ] **Step 5: 实现域名写操作**

新增域名使用小型弹窗；编辑域名复用同一表单；“设为主域名”调用 PATCH `{ is_primary: true }`；删除使用 `Popconfirm`。操作成功后刷新详情和父列表。主域名永远不渲染删除按钮。

- [ ] **Step 6: 编写公司停用/启用失败测试**

在公司列表中测试：停用必须二次确认并发送 `{ status: 'inactive' }`；取消不得请求；停用公司可直接选择启用并发送 `{ status: 'active' }`；操作后刷新列表。

- [ ] **Step 7: 实现公司状态变更**

active 行显示“停用”危险操作并使用 `Popconfirm`，确认文案说明用户将不能登录或访问业务接口；inactive 行显示“启用”。请求失败保留原状态并显示中文错误。

- [ ] **Step 8: 运行平台页面全部测试**

Run: `cd frontend && npm test -- src/pages/Platform/Tenants.test.tsx src/pages/Platform/TenantDetailDrawer.test.tsx`

Expected: 全部通过。

- [ ] **Step 9: 提交公司维护增量**

```bash
git add frontend/src/pages/Platform/Tenants.tsx frontend/src/pages/Platform/Tenants.test.tsx frontend/src/pages/Platform/TenantDetailDrawer.tsx frontend/src/pages/Platform/TenantDetailDrawer.test.tsx frontend/src/pages/Platform/platform.css
git commit -m "feat: manage platform tenants and domains"
```

---

### Task 5: 完整验证和本地部署

**Files:**
- Modify only if tests expose a defect in files from Tasks 1-4.

**Interfaces:**
- Consumes: 全部平台控制台文件和现有 Docker Compose 服务。
- Produces: 可通过 `https://interview-local.careray.com/platform/login` 访问的平台控制台。

- [ ] **Step 1: 运行平台定向测试**

Run:

```bash
cd frontend
npm test -- src/utils/platformRequest.test.ts src/contexts/PlatformAuthContext.test.tsx src/components/Platform/PlatformProtectedRoute.test.tsx src/pages/Platform/Login.test.tsx src/pages/Platform/Tenants.test.tsx src/pages/Platform/TenantDetailDrawer.test.tsx
```

Expected: 全部通过，0 failed。

- [ ] **Step 2: 运行完整前端测试**

Run: `cd frontend && npm test`

Expected: 全部通过，0 failed。

- [ ] **Step 3: 运行 TypeScript 和 Vite 构建**

Run: `cd frontend && npm run build`

Expected: exit 0，生成 `frontend/dist`。

- [ ] **Step 4: 检查差异和敏感信息**

Run:

```bash
git diff --check
git status --short
rg -n "platform_token|localStorage\.getItem\('token'\)" frontend/src/utils frontend/src/contexts frontend/src/pages/Platform
```

Expected: 无空白错误；平台模块不存在读取普通业务 token 的代码；没有硬编码密码或 JWT。

- [ ] **Step 5: 重建并启动本地前端**

在保留当前数据库和后端容器的前提下，使用当前 Compose 项目重建 `frontend`，随后确认 `ai_interview_frontend` 和 `ai_interview_caddy` 为 Up，`ai_interview_backend` 为 healthy。

- [ ] **Step 6: HTTPS 冒烟测试**

Run:

```bash
curl -k --resolve interview-local.careray.com:443:127.0.0.1 -I https://interview-local.careray.com/platform/login
curl -k --resolve interview-local.careray.com:443:127.0.0.1 https://interview-local.careray.com/api/auth/tenants
```

Expected: 两个请求均返回 HTTP 200；平台页面为 HTML，公司列表接口仍为 JSON。

- [ ] **Step 7: 验证平台登录接口边界**

向平台登录接口提交无效测试凭据，确认返回统一的 401 且响应不泄露账号是否存在。首个平台管理员不在自动测试中创建，避免在用户未指定邮箱和密码时改变平台身份数据；页面功能通过前端交互测试和现有后端平台 API 测试完成验证。

- [ ] **Step 8: 提交最终验证修正**

若本任务产生修正：

```bash
git add frontend/src
git commit -m "fix: complete platform console verification"
```

若没有文件变化，则不创建空提交。
