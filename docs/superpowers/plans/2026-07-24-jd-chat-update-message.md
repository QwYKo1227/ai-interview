# JD Chat Update Message Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the JD chat success reply accurately tell users that the updated job description appears above the conversation.

**Architecture:** Keep the existing frontend-only success flow and layout. Add a dependency-free Node static regression test for the user-facing copy, then replace the single fixed message and verify the production bundle and running frontend container.

**Tech Stack:** React 19, TypeScript 5.9, Vite 7, Node.js built-in test runner, Docker Compose

## Global Constraints

- The exact success copy is `已根据您的要求更新了上方岗位描述。`.
- Only show this copy in the existing branch that successfully parses and applies the returned JD.
- Do not change the modal layout, backend prompt, API shape, database, or multi-tenant behavior.

---

### Task 1: Protect and update the JD success copy

**Files:**
- Create: `frontend/tests/jd-chat-update-message.test.mjs`
- Modify: `frontend/src/components/JDGeneratorModal/index.tsx:195`

**Interfaces:**
- Consumes: The existing `data.done` success branch in `handleChat`.
- Produces: An assistant chat message whose content is exactly `已根据您的要求更新了上方岗位描述。`.

- [ ] **Step 1: Write the failing static regression test**

```javascript
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const componentUrl = new URL('../src/components/JDGeneratorModal/index.tsx', import.meta.url);

test('JD chat success message points to the updated content above', async () => {
  const source = await readFile(componentUrl, 'utf8');

  assert.match(source, /已根据您的要求更新了上方岗位描述。/);
  assert.doesNotMatch(source, /已根据您的要求更新了岗位描述，请查看下方内容。/);
});
```

- [ ] **Step 2: Run the test and verify the RED state**

Run: `node --test tests/jd-chat-update-message.test.mjs` from `frontend/`.

Expected: FAIL because the component does not yet contain `已根据您的要求更新了上方岗位描述。`.

- [ ] **Step 3: Replace only the fixed assistant success message**

Change the existing assistant message inside the `data.done` branch to:

```typescript
{ role: 'assistant', content: '已根据您的要求更新了上方岗位描述。' },
```

- [ ] **Step 4: Run the focused test and production build**

Run from `frontend/`:

```powershell
node --test tests/jd-chat-update-message.test.mjs
npm run build
```

Expected: The Node test reports 1 passing test, and the TypeScript/Vite production build exits with code 0.

- [ ] **Step 5: Commit the tested code change**

```powershell
git add frontend/tests/jd-chat-update-message.test.mjs frontend/src/components/JDGeneratorModal/index.tsx
git commit -m "fix: clarify JD chat update location"
```

### Task 2: Rebuild and verify the frontend test container

**Files:**
- Modify: none

**Interfaces:**
- Consumes: `ai-interview-frontend:latest`, Compose project `ai-interview-main`, and `APP_DOMAIN=interview-local.careray.com` from the root `.env`.
- Produces: A running frontend container serving the new success copy at `https://interview-local.careray.com`.

- [ ] **Step 1: Rebuild the frontend image from the fix worktree**

Run from the worktree root:

```powershell
docker compose -p ai-interview-main --env-file "E:\ai-interview-main\.env" -f docker-compose.prod.yml build frontend
```

Expected: The image `ai-interview-frontend:latest` builds successfully.

- [ ] **Step 2: Recreate only the frontend service**

```powershell
docker compose -p ai-interview-main --env-file "E:\ai-interview-main\.env" -f docker-compose.prod.yml up -d --no-build --no-deps frontend
```

Expected: `ai_interview_frontend` is recreated without touching the backend or database containers.

- [ ] **Step 3: Verify the public site and running assets**

```powershell
curl.exe -k -sS -o NUL -w "site=%{http_code}`n" https://interview-local.careray.com/
docker exec ai_interview_frontend sh -lc "grep -R -l '已根据您的要求更新了上方岗位描述。' /usr/share/nginx/html/assets | wc -l"
docker exec ai_interview_frontend sh -lc "grep -R -l '已根据您的要求更新了岗位描述，请查看下方内容。' /usr/share/nginx/html/assets 2>/dev/null | wc -l"
```

Expected: The site returns HTTP 200, the new-copy count is at least 1, and the old-copy count is 0.

- [ ] **Step 4: Confirm unrelated container state was preserved**

```powershell
docker inspect ai_interview_backend --format 'backend={{.State.Status}}/{{.State.Health.Status}} restarts={{.RestartCount}} started={{.State.StartedAt}}'
docker inspect ai_interview_db --format 'database={{.State.Status}}/{{.State.Health.Status}} restarts={{.RestartCount}} started={{.State.StartedAt}}'
```

Expected: Both containers remain running and healthy; neither is recreated while deploying this frontend-only change.
