# Unified Company Login Domain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make both deployment login domains shared company-selection entry points, remove domain-based company locking, and keep the platform administrator link without its explanatory copy.

**Architecture:** The login form will always submit an explicitly user-selected `tenant_code`; browser hostname will no longer alter form state. The backend's existing unified-host policy remains the authority for shared domains, while production Compose makes `UNIFIED_ENTRY_HOSTS` mandatory and environment examples supply the correct production value.

**Tech Stack:** React 19, TypeScript, Ant Design, Vitest, Testing Library, FastAPI, pytest, Docker Compose.

## Global Constraints

- Production login URL is `https://interview.careray.com/login`.
- Development/test login URL is `https://interview-local.careray.com/login`.
- Every company must be selected manually from the same login page, regardless of how many companies exist.
- Do not change tenant isolation, JWT validation, user credentials, or platform administrator authentication.
- Unknown hosts must remain rejected unless explicitly configured as unified hosts or tenant domains.

---

## File Structure

- `frontend/src/pages/Login/index.tsx`: owns login form state, tenant selection, and the platform administrator entry link.
- `frontend/src/pages/Login/Login.test.tsx`: specifies user-visible login behavior and routing from the login card.
- `.env.example`: documents the production shared-login host.
- `.env`: supplies the local Docker production-like environment's shared-login host; it remains untracked and must not be committed.
- `docker-compose.prod.yml`: requires the shared-host setting instead of silently accepting an empty value.
- `backend/tests/test_tenant_migration_verifier.py`: guards deploy-time configuration contracts.
- `backend/tests/test_tenant_auth.py`: verifies a configured shared domain allows login to a company other than the domain's historical tenant mapping.

### Task 1: Remove browser-domain company locking

**Files:**
- Modify: `frontend/src/pages/Login/Login.test.tsx`
- Modify: `frontend/src/pages/Login/index.tsx`

**Interfaces:**
- Consumes: `GET /auth/tenants -> TenantSummary[]` and Ant Design form field `tenant_code`.
- Produces: a company `<select aria-label="公司">` disabled only while tenants are loading and never preselected from `window.location.hostname`.

- [ ] **Step 1: Replace the dedicated-domain test with a failing shared-entry test**

```tsx
it('keeps company selection manual when the login host matches a company domain', async () => {
  const tenant = { id: '1', code: 'careray', name: '凯锐招聘', primary_domain: 'interview.careray.com' };
  mockGet.mockResolvedValueOnce([tenant]);
  mockResolveTenantSelection.mockReturnValueOnce(tenant);

  renderLogin();

  const company = await screen.findByLabelText('公司');
  expect(company).toBeEnabled();
  expect(company).toHaveValue('');
  expect(screen.queryByText(/当前专属域名已锁定公司/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test and verify RED**

Run: `npm test -- src/pages/Login/Login.test.tsx` from `frontend/`.

Expected: FAIL because the company is selected, disabled, and the lock message exists.

- [ ] **Step 3: Remove hostname-driven state from the login component**

Delete the `resolveTenantSelection` import, the `lockedTenant` state, the call that resolves `window.location.hostname`, and the conditional lock-status block. Change the select condition to:

```tsx
disabled={tenantsLoading}
```

After loading tenants, retain only:

```tsx
const nextTenants = Array.isArray(response) ? response : [];
setTenants(nextTenants);
```

- [ ] **Step 4: Remove obsolete test mocks and run GREEN**

Delete the `resolveTenantSelection` import, module mock, typed mock, and per-host parameterized test from `Login.test.tsx`.

Run: `npm test -- src/pages/Login/Login.test.tsx` from `frontend/`.

Expected: all login component tests PASS.

- [ ] **Step 5: Commit the focused frontend behavior change**

```bash
git add frontend/src/pages/Login/index.tsx frontend/src/pages/Login/Login.test.tsx
git commit -m "fix: keep company selection manual on shared login"
```

### Task 2: Retain the platform entry without explanatory copy

**Files:**
- Modify: `frontend/src/pages/Login/Login.test.tsx`
- Modify: `frontend/src/pages/Login/index.tsx`

**Interfaces:**
- Consumes: React Router `Link` and route `/platform/login`.
- Produces: visible link named `平台管理员入口`; must not render `用于公司开通、域名与企业管理员管理`.

- [ ] **Step 1: Write the failing platform-entry test**

Update the test router to include `/login` and `/platform/login`, then add:

```tsx
it('opens platform login without showing the management-purpose description', async () => {
  mockGet.mockResolvedValueOnce([]);
  const user = userEvent.setup();

  renderLogin();

  expect(screen.queryByText('用于公司开通、域名与企业管理员管理')).not.toBeInTheDocument();
  await user.click(await screen.findByRole('link', { name: '平台管理员入口' }));
  expect(await screen.findByText('平台登录页面')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test and verify RED**

Run: `npm test -- src/pages/Login/Login.test.tsx` from `frontend/`.

Expected: FAIL because the `平台管理员入口` link is absent on `main`.

- [ ] **Step 3: Add only the platform link**

Import `Link` from `react-router-dom` and append this block after the login form:

```tsx
<div
  style={{
    borderTop: '1px solid var(--border-color)',
    marginTop: 8,
    paddingTop: 18,
    textAlign: 'center',
  }}
>
  <Link to="/platform/login" style={{ display: 'inline-block', fontWeight: 600, padding: '4px 8px' }}>
    平台管理员入口
  </Link>
</div>
```

Do not add the removed explanatory `Text` node.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `npm test -- src/pages/Login/Login.test.tsx` from `frontend/`.

Expected: all login component tests PASS.

- [ ] **Step 5: Commit the platform-entry copy change**

```bash
git add frontend/src/pages/Login/index.tsx frontend/src/pages/Login/Login.test.tsx
git commit -m "feat: add concise platform login entry"
```

### Task 3: Make shared-host deployment configuration explicit

**Files:**
- Modify: `backend/tests/test_tenant_migration_verifier.py`
- Modify: `backend/tests/test_tenant_auth.py`
- Modify: `.env.example`
- Modify: `.env` (local only; do not stage)
- Modify: `docker-compose.prod.yml`

**Interfaces:**
- Consumes: environment variable `UNIFIED_ENTRY_HOSTS`, parsed by `app.core.host_policy.configured_unified_hosts()`.
- Produces: production example value `interview.careray.com`, local runtime value `interview-local.careray.com`, and a Compose startup error when the variable is missing.

- [ ] **Step 1: Write failing configuration contract assertions**

Extend `test_production_caddy_defaults_to_both_internal_tenant_domains` with:

```python
env_example = (root / ".env.example").read_text(encoding="utf-8")
assert "UNIFIED_ENTRY_HOSTS=interview.careray.com" in env_example
assert (
    "UNIFIED_ENTRY_HOSTS: ${UNIFIED_ENTRY_HOSTS:?Set UNIFIED_ENTRY_HOSTS "
    "to the shared company login hostname}" in compose
)
```

- [ ] **Step 2: Run the configuration guard and verify RED**

Run: `pytest backend/tests/test_tenant_migration_verifier.py::test_production_caddy_defaults_to_both_internal_tenant_domains -q` from the repository root.

Expected: FAIL because `.env.example` contains an empty value and Compose permits an empty default.

- [ ] **Step 3: Verify the existing host policy supports the intended data flow**

Add this regression test to `backend/tests/test_tenant_auth.py`:

```python
def test_shared_login_domain_allows_company_selection_despite_domain_mapping(
    client, db, tenant_a, tenant_b, monkeypatch
):
    monkeypatch.setenv("UNIFIED_ENTRY_HOSTS", "interview.careray.com")
    create_user(db, tenant_b.id, "member@example.com", "Password123")
    db.add(
        TenantDomain(
            tenant_id=tenant_a.id,
            domain="interview.careray.com",
            is_primary=True,
        )
    )
    db.commit()

    response = client.post(
        "/api/auth/login",
        headers={"Host": "interview.careray.com"},
        json={
            "tenant_code": tenant_b.code,
            "email": "member@example.com",
            "password": "Password123",
        },
    )

    assert response.status_code == 200
```

Run: `pytest backend/tests/test_tenant_auth.py::test_shared_login_domain_allows_company_selection_despite_domain_mapping -q`.

Expected: PASS, demonstrating no backend code change is necessary once configuration is correct.

- [ ] **Step 4: Apply the minimal deployment configuration**

Change tracked production configuration to:

```dotenv
UNIFIED_ENTRY_HOSTS=interview.careray.com
```

```yaml
UNIFIED_ENTRY_HOSTS: ${UNIFIED_ENTRY_HOSTS:?Set UNIFIED_ENTRY_HOSTS to the shared company login hostname}
```

Add or update the untracked local `.env` entry to:

```dotenv
UNIFIED_ENTRY_HOSTS=interview-local.careray.com
```

- [ ] **Step 5: Run both backend tests and verify GREEN**

Run:

```bash
pytest backend/tests/test_tenant_migration_verifier.py::test_production_caddy_defaults_to_both_internal_tenant_domains backend/tests/test_tenant_auth.py::test_shared_login_domain_allows_company_selection_despite_domain_mapping -q
```

Expected: 2 passed.

- [ ] **Step 6: Commit tracked configuration and tests only**

```bash
git add .env.example docker-compose.prod.yml backend/tests/test_tenant_migration_verifier.py backend/tests/test_tenant_auth.py
git commit -m "fix: configure shared company login host"
```

### Task 4: Final regression verification

**Files:**
- Verify: all files changed in Tasks 1-3.

**Interfaces:**
- Consumes: completed frontend and deployment changes.
- Produces: evidence that the focused tests, frontend build, and backend related suite pass together.

- [ ] **Step 1: Run frontend focused tests and build**

Run from `frontend/`:

```bash
npm test -- src/pages/Login/Login.test.tsx
npm run build
```

Expected: login tests PASS and the TypeScript/Vite build completes successfully.

- [ ] **Step 2: Run backend host, auth, and operational guards**

Run from the repository root:

```bash
pytest backend/tests/test_tenant_auth.py backend/tests/test_tenant_migration_verifier.py backend/tests/test_operational_guards.py -q
```

Expected: all selected backend tests PASS.

- [ ] **Step 3: Validate the final diff**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only the pre-existing untracked `backups/` directory and the intentionally untracked local `.env` state remain outside committed work.
