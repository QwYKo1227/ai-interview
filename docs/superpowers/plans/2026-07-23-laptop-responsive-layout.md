# Laptop Responsive Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep management-page actions visible on 1280×720 and 1366×768 laptop viewports while preserving the resume detail's side-by-side comparison layout.

**Architecture:** Use Ant Design's `xxl` breakpoint as the single source of truth for automatic sidebar collapse and compact page spacing. Constrain wide business content inside its own containers: the positions table gets local horizontal scrolling and a fixed action column, while the resume detail keeps two shrinkable flex panes and moves actions into a wrapping row.

**Tech Stack:** React 19, TypeScript 5.9, Ant Design 6, Vite 7, Vitest, Testing Library, jsdom.

## Global Constraints

- At 1280×720, 1366×768, and normal large-screen viewports, the page shell must not create horizontal scrolling.
- The sidebar automatically collapses at laptop width and shows the full menu label on hover or keyboard focus.
- The positions table may scroll horizontally only inside its table container, with the action column visible on the right.
- The resume detail must remain a left/right split at laptop widths.
- Existing API requests, authorization checks, button order, and button behavior must not change.
- Existing large-screen colors, typography, and overall structure must remain unchanged.

---

### Task 1: Frontend Test Harness

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/test/setup.ts`

**Interfaces:**
- Consumes: the existing Vite/React configuration.
- Produces: `npm test -- --run` and a jsdom environment shared by component tests.

- [ ] **Step 1: Add the test script and development dependencies**

Run:

```powershell
Set-Location frontend
npm install --save-dev vitest jsdom @testing-library/react @testing-library/jest-dom
```

Then add this script to `package.json`:

```json
"test": "vitest"
```

Expected: `package.json` and `package-lock.json` contain Vitest, jsdom, and Testing Library.

- [ ] **Step 2: Configure Vitest**

Update `vite.config.ts` to include the test setup:

```ts
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/uploads': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
  },
})
```

- [ ] **Step 3: Add browser API shims**

Create `frontend/src/test/setup.ts`:

```ts
import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.stubGlobal('ResizeObserver', ResizeObserverMock)
vi.stubGlobal('scrollTo', vi.fn())
```

- [ ] **Step 4: Verify the harness**

Run:

```powershell
npm test -- --run --passWithNoTests
```

Expected: PASS with exit code 0 and no test files found.

- [ ] **Step 5: Commit the harness**

```powershell
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/src/test/setup.ts
git commit -m "test: add frontend component test harness"
```

---

### Task 2: Automatic Sidebar Collapse and Accessible Labels

**Files:**
- Create: `frontend/src/components/Layout/index.test.tsx`
- Modify: `frontend/src/components/Layout/index.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: `Grid.useBreakpoint()` from Ant Design and existing menu item labels.
- Produces: `.app-sider`, `.app-main-layout`, `.app-header`, and `.app-content` whose widths track the `xxl` breakpoint; collapsed menu items retain `title` and `aria-label` text.

- [ ] **Step 1: Write the failing layout tests**

Create `frontend/src/components/Layout/index.test.tsx` with a hoisted screen-state mock, an authenticated user mock, and these assertions:

```tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AppLayout from './index'

const screenState = vi.hoisted(() => ({ xxl: false }))

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd')
  return {
    ...actual,
    Grid: { ...actual.Grid, useBreakpoint: () => ({ xxl: screenState.xxl }) },
  }
})

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', email: 'admin@example.com', full_name: 'HR Admin', role: 'admin' },
    logout: vi.fn(),
  }),
}))

describe('AppLayout responsiveness', () => {
  beforeEach(() => { screenState.xxl = false })

  it('collapses the sidebar and synchronizes the content offset on laptop screens', () => {
    const { container } = render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)
    expect(container.querySelector('.app-sider')).toHaveClass('ant-layout-sider-collapsed')
    expect(container.querySelector('.app-main-layout')).toHaveStyle({ marginLeft: '80px' })
  })

  it('keeps full menu names available in collapsed mode', () => {
    render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)
    expect(screen.getByLabelText('岗位管理')).toBeVisible()
  })

  it('uses the expanded sidebar on large screens', () => {
    screenState.xxl = true
    const { container } = render(<MemoryRouter initialEntries={['/positions']}><AppLayout /></MemoryRouter>)
    expect(container.querySelector('.app-sider')).not.toHaveClass('ant-layout-sider-collapsed')
    expect(container.querySelector('.app-main-layout')).toHaveStyle({ marginLeft: '240px' })
  })
})
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
npm test -- --run src/components/Layout/index.test.tsx
```

Expected: FAIL because the sidebar is not breakpoint-controlled, `.app-main-layout` does not exist, and collapsed menu items have no accessible label contract.

- [ ] **Step 3: Implement breakpoint-controlled layout**

In `Layout/index.tsx`, import `Grid`, derive `const isLaptop = !Grid.useBreakpoint().xxl`, add `collapsed={isLaptop}`, `collapsedWidth={80}`, and `trigger={null}` to the sider, and synchronize the main layout offset:

```tsx
const screens = Grid.useBreakpoint()
const isLaptop = !screens.xxl
const siderWidth = isLaptop ? 80 : 240

<Sider
  className="app-sider"
  collapsed={isLaptop}
  collapsedWidth={80}
  trigger={null}
  width={240}
  // preserve existing visual styles
>

<Layout className="app-main-layout" style={{ marginLeft: siderWidth }}>
```

Add these attributes to the existing header and content opening tags without changing their children:

```tsx
className="app-header"
className="app-content"
```

Wrap each icon with the existing item label only in collapsed mode, so the same text drives both the visual Tooltip and accessible name:

```tsx
const menuItems = rawMenuItems.map((item) => ({
  ...item,
  icon: isLaptop ? (
    <Tooltip title={item.label} placement="right">
      <span className="collapsed-menu-icon" aria-label={item.label} tabIndex={0}>
        {item.icon}
      </span>
    </Tooltip>
  ) : item.icon,
}))
```

- [ ] **Step 4: Add compact laptop spacing**

Add to `index.css`:

```css
.app-main-layout {
  min-width: 0;
  transition: margin-left 0.2s ease;
}

.app-content {
  min-width: 0;
}

.app-user-name {
  display: inline-block;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

@media (max-width: 1599px) {
  .app-header {
    padding-inline: 20px !important;
  }

  .app-content {
    margin: 20px !important;
  }
}
```

- [ ] **Step 5: Run the tests and verify GREEN**

Run:

```powershell
npm test -- --run src/components/Layout/index.test.tsx
```

Expected: all three layout tests PASS.

- [ ] **Step 6: Commit the layout change**

```powershell
git add frontend/src/components/Layout/index.tsx frontend/src/components/Layout/index.test.tsx frontend/src/index.css
git commit -m "fix: adapt application shell to laptop widths"
```

---

### Task 3: Contained Positions Table Actions

**Files:**
- Create: `frontend/src/pages/Positions/List.test.tsx`
- Modify: `frontend/src/pages/Positions/List.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: the existing position columns and action callbacks.
- Produces: a table with `scroll.x = 1180`, an action column with `width = 200` and `fixed = 'right'`, plus wrapping title and filter toolbars.

- [ ] **Step 1: Write the failing table test**

Create `frontend/src/pages/Positions/List.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import PositionsList from './List'
import request from '../../utils/request'

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('../../components/JDGeneratorModal', () => ({ default: () => null }))

describe('PositionsList responsive table', () => {
  it('contains horizontal overflow and fixes the action column to the right', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => url === '/positions' ? [] : [])
    const { container } = render(<MemoryRouter><PositionsList /></MemoryRouter>)
    await waitFor(() => expect(request.get).toHaveBeenCalledWith('/positions', expect.any(Object)))
    const actionHeader = screen.getByRole('columnheader', { name: '操作' })
    expect(actionHeader).toHaveClass('ant-table-cell-fix-right')
    expect(container.querySelector('.positions-table')).toBeInTheDocument()
    expect(container.querySelector('.ant-table-content')).toHaveStyle({ overflowX: 'auto' })
  })
})
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
npm test -- --run src/pages/Positions/List.test.tsx
```

Expected: FAIL because the action column is not fixed and the table has no local horizontal scroll configuration.

- [ ] **Step 3: Constrain the table and action column**

Insert the following properties into the existing action column immediately after `key: 'action'`; leave its existing `render` callback unchanged:

```tsx
width: 200,
fixed: 'right' as const,
```

Give the main columns explicit widths totaling approximately 1180px, add `className="positions-table"`, and configure local scrolling:

```tsx
<Table
  className="positions-table"
  columns={columns}
  dataSource={data}
  scroll={{ x: 1180 }}
  // preserve loading, key, pagination, and selection props
/>
```

Add classes to the page title row and filter row instead of relying solely on anonymous inline flex containers.

- [ ] **Step 4: Add wrapping safeguards**

Add to `index.css`:

```css
.positions-page-header,
.positions-filter-bar {
  min-width: 0;
  flex-wrap: wrap;
}

.positions-table {
  min-width: 0;
  max-width: 100%;
}

.positions-table .ant-table-cell-fix-right {
  background: var(--surface-color);
}
```

- [ ] **Step 5: Run the test and verify GREEN**

Run:

```powershell
npm test -- --run src/pages/Positions/List.test.tsx
```

Expected: the positions responsive-table test PASS.

- [ ] **Step 6: Commit the table change**

```powershell
git add frontend/src/pages/Positions/List.tsx frontend/src/pages/Positions/List.test.tsx frontend/src/index.css
git commit -m "fix: contain position table actions on small screens"
```

---

### Task 4: Shrinkable Two-Pane Resume Detail

**Files:**
- Create: `frontend/src/pages/Resumes/Detail.test.tsx`
- Modify: `frontend/src/pages/Resumes/Detail.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: the existing resume payload, status mapping, and action rendering.
- Produces: `.resume-detail-split` with two `.resume-detail-pane` children and a separate `.resume-detail-actions` wrapping row inside the right pane.

- [ ] **Step 1: Write the failing two-pane test**

Create `frontend/src/pages/Resumes/Detail.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import ResumeDetail from './Detail'
import request from '../../utils/request'

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}))

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'admin-1', role: 'admin' } }),
}))

const resume = {
  id: 'resume-1',
  candidate_name: '冯云龙',
  email: 'candidate@example.com',
  contact: '13800000000',
  status: 'pending_review',
  parse_status: 'success',
  match_score: 68,
  file_path: 'uploads/resume.pdf',
  parsed_data: {},
  position: { title: '测试工程师' },
  department_reviews: [],
}

describe('ResumeDetail laptop layout', () => {
  it('keeps two shrinkable panes and wraps actions inside the analysis pane', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/resume-1') return resume
      if (url === '/auth/interviewers') return []
      return {}
    })

    const { container } = render(
      <MemoryRouter initialEntries={['/resumes/resume-1']}>
        <Routes><Route path="/resumes/:id" element={<ResumeDetail />} /></Routes>
      </MemoryRouter>,
    )

    await screen.findByText('冯云龙')
    const split = container.querySelector('.resume-detail-split')
    expect(split).toBeInTheDocument()
    expect(split).toHaveStyle({ flexDirection: 'row' })
    expect(container.querySelectorAll('.resume-detail-pane')).toHaveLength(2)
    expect(container.querySelector('.resume-detail-actions')).toHaveStyle({ flexWrap: 'wrap' })
  })
})
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
npm test -- --run src/pages/Resumes/Detail.test.tsx
```

Expected: FAIL because the split panes and wrapping action row do not have the required structure.

- [ ] **Step 3: Keep both panes shrinkable**

Add the following class names and `flexDirection` property to the existing split wrapper and its two existing child wrappers; do not move their children:

```tsx
className="resume-detail-split"
style={{ flex: 1, display: 'flex', flexDirection: 'row', gap: 24, overflow: 'hidden' }}

className="resume-detail-pane resume-preview-pane"

className="resume-detail-pane resume-analysis-pane"
```

Add to `index.css`:

```css
.resume-detail-split,
.resume-detail-pane {
  min-width: 0;
}

.resume-detail-pane {
  flex: 1 1 0;
}
```

- [ ] **Step 4: Split metadata from actions**

Keep candidate information, match score, and status in the first header row. Add these attributes to their existing wrappers and move the existing `renderActionButtons()` call, unchanged, to the sibling action row shown last:

```tsx
className="resume-detail-heading"
className="resume-detail-candidate"
className="resume-detail-summary"

<Space className="resume-detail-actions" wrap>
  {renderActionButtons()}
</Space>
```

Add the layout rules:

```css
.resume-detail-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  min-width: 0;
  margin-bottom: 16px;
}

.resume-detail-candidate {
  flex: 1 1 auto;
  min-width: 0;
}

.resume-detail-summary {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 12px;
}

.resume-detail-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  margin-bottom: 24px;
}

@media (max-width: 1599px) {
  .resume-detail-split { gap: 16px !important; }
  .resume-detail-heading { flex-wrap: wrap; }
  .resume-detail-actions { justify-content: flex-start; }
}
```

Apply `min-width: 0` and `flex-wrap: wrap` to the left preview header so its title and download button cannot widen the pane.

- [ ] **Step 5: Run the test and verify GREEN**

Run:

```powershell
npm test -- --run src/pages/Resumes/Detail.test.tsx
```

Expected: the resume detail layout test PASS while the DOM retains two sibling panes.

- [ ] **Step 6: Commit the resume detail change**

```powershell
git add frontend/src/pages/Resumes/Detail.tsx frontend/src/pages/Resumes/Detail.test.tsx frontend/src/index.css
git commit -m "fix: preserve responsive resume comparison panes"
```

---

### Task 5: Regression and Visual Verification

**Files:**
- Modify only if verification exposes a defect in files already listed above.

**Interfaces:**
- Consumes: all preceding responsive layout changes.
- Produces: passing automated checks and viewport evidence for the stated acceptance sizes.

- [ ] **Step 1: Run all component tests**

Run:

```powershell
Set-Location frontend
npm test -- --run
```

Expected: all layout, positions, and resume detail tests PASS with no unhandled errors.

- [ ] **Step 2: Run static and production checks**

Run:

```powershell
npm run lint
npm run build
```

Expected: both commands exit 0. Any pre-existing warning must be recorded separately; no new warning may be introduced.

- [ ] **Step 3: Inspect the target viewports**

Start the existing application stack, authenticate with available local demo data, and inspect `/positions` and one `/resumes/:id` page at:

```text
1280 × 720
1366 × 768
1920 × 1080
```

At each size, evaluate:

```js
({
  viewport: [window.innerWidth, window.innerHeight],
  pageOverflows: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  sidebarCollapsed: document.querySelector('.app-sider')?.classList.contains('ant-layout-sider-collapsed'),
  resumePaneCount: document.querySelectorAll('.resume-detail-pane').length,
})
```

Expected at 1280 and 1366: `pageOverflows` is `false`, `sidebarCollapsed` is `true`, and resume detail reports `resumePaneCount: 2`. Expected at 1920: `pageOverflows` is `false` and `sidebarCollapsed` is `false`.

- [ ] **Step 4: Verify interaction details**

On laptop widths:

- Hover each collapsed navigation icon and confirm the complete Chinese menu label appears.
- Tab through the navigation and confirm focused items expose the complete accessible name.
- Scroll the positions table horizontally and confirm the action column remains visible.
- Confirm all resume actions remain inside the analysis pane and wrap without covering status or match score.

- [ ] **Step 5: Commit verification-only fixes if needed**

If verification required code adjustments, rerun Steps 1–4 and commit only those adjustments:

```powershell
git add frontend/src/components/Layout/index.tsx frontend/src/pages/Positions/List.tsx frontend/src/pages/Resumes/Detail.tsx frontend/src/index.css
git commit -m "fix: polish laptop responsive layout"
```
