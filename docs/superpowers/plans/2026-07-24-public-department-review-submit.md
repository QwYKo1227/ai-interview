# Public Department Review Submit Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the successful public department review submission from showing a false `Public resource not found` error and add semantic green, red, and yellow borders to the recommendation buttons.

**Architecture:** Keep the backend's one-time-token revocation unchanged. After the POST succeeds, transition the React page to its existing completed state locally instead of issuing another GET with the revoked token; keep recommendation colors as explicit inline button styles so the selected and unselected states share the same semantic border.

**Tech Stack:** React 19, TypeScript, Ant Design 6, React Router 7, Vitest 4, Testing Library

## Global Constraints

- Do not change public-token lifetime or revocation semantics.
- Do not change backend review submission schemas or responses.
- Do not redesign the rest of the public review page.
- Use green `#52c41a` for 推荐, red `#ff4d4f` for 不推荐, and yellow `#faad14` for 待定.

---

## File Structure

- Create `frontend/src/pages/Public/Review.test.tsx`: regression coverage for successful submission state transition and recommendation button border colors.
- Modify `frontend/src/pages/Public/Review.tsx`: replace the post-submit refetch with a local completed state and apply the semantic button styles.

### Task 1: Complete Locally After a Successful Submission

**Files:**
- Create: `frontend/src/pages/Public/Review.test.tsx`
- Modify: `frontend/src/pages/Public/Review.tsx`

**Interfaces:**
- Consumes: `request.get(url: string)` and `request.post(url: string, payload: object)` from `frontend/src/utils/request.ts`.
- Produces: the existing completed-review result whenever `existingReview.is_completed` becomes `true`; no new exported API.

- [ ] **Step 1: Write the failing submission regression test**

Create `frontend/src/pages/Public/Review.test.tsx` with the following test harness and first test:

```tsx
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PublicReview from './Review'
import request from '../../utils/request'

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

const reviewPayload = {
  resume: {
    id: 'resume-1',
    candidate_name: '测试候选人',
    email: 'candidate@example.com',
    contact: '13800000000',
    match_score: 88,
    ai_review: '',
    resume_markdown: '',
    parsed_data: {},
    position: {
      id: 'position-1',
      title: '测试工程师',
      description: '',
      requirements: '',
    },
    status: 'pending_dept_review',
    department_reviews: [],
  },
  existing_review: {
    id: 'review-1',
    technical_score: 0,
    experience_score: 0,
    overall_score: 0,
    recommendation: null,
    comment: null,
    is_completed: false,
  },
}

const renderReview = () => render(
  <MemoryRouter initialEntries={['/public/review/public-token']}>
    <Routes>
      <Route path="/public/review/:token" element={<PublicReview />} />
    </Routes>
  </MemoryRouter>,
)

describe('PublicReview', () => {
  beforeEach(() => {
    vi.mocked(request.get).mockReset().mockResolvedValue(reviewPayload)
    vi.mocked(request.post).mockReset().mockResolvedValue({
      message: 'Review submitted',
      review_id: 'review-1',
    })
  })

  afterEach(() => cleanup())

  it('shows completion without refetching the revoked public token', async () => {
    renderReview()

    await screen.findByText('测试候选人')
    fireEvent.click(screen.getByRole('button', { name: '推荐' }))
    fireEvent.click(screen.getByRole('button', { name: '提交审核' }))

    await screen.findByText('审核已完成')
    expect(request.post).toHaveBeenCalledWith('/public/review/public-token/submit', {
      technical_score: 0,
      experience_score: 0,
      overall_score: 0,
      recommendation: 'recommend',
      comment: '',
    })
    await waitFor(() => expect(request.get).toHaveBeenCalledTimes(1))
  })
})
```

- [ ] **Step 2: Run the targeted test and verify RED**

Run:

```powershell
npm test -- src/pages/Public/Review.test.tsx
```

from `frontend/`.

Expected: FAIL because the successful POST calls `fetchResume()` again, causing `request.get` to be called twice instead of once (and the mocked incomplete payload prevents the completed result from appearing).

- [ ] **Step 3: Implement the minimal local completion transition**

In `frontend/src/pages/Public/Review.tsx`, replace the successful-submit refetch:

```tsx
message.success('审核已提交')
fetchResume()
```

with:

```tsx
message.success('审核已提交')
setExistingReview((current: any) => ({
  ...(current || {}),
  is_completed: true,
}))
```

Do not change the catch or finally blocks. This ensures failed POST requests retain the form and only a successful POST triggers the completed result.

- [ ] **Step 4: Run the targeted test and verify GREEN**

Run:

```powershell
npm test -- src/pages/Public/Review.test.tsx
```

Expected: PASS with one GET, one POST, and the completed-review result visible.

- [ ] **Step 5: Commit the submission fix**

```powershell
git add -- frontend/src/pages/Public/Review.tsx frontend/src/pages/Public/Review.test.tsx
git commit -m "fix: complete public review without revoked token refetch"
```

### Task 2: Add Semantic Recommendation Borders

**Files:**
- Modify: `frontend/src/pages/Public/Review.test.tsx`
- Modify: `frontend/src/pages/Public/Review.tsx`

**Interfaces:**
- Consumes: the existing `recommendation` state values `recommend`, `not_recommend`, and `pending`.
- Produces: inline `borderColor` styles with exact semantic color values and matching selected-state backgrounds.

- [ ] **Step 1: Write the failing border-color test**

Add this test inside the existing `describe('PublicReview', ...)` block in `frontend/src/pages/Public/Review.test.tsx`:

```tsx
it('uses semantic border colors for every recommendation option', async () => {
  renderReview()

  await screen.findByText('测试候选人')
  expect(screen.getByRole('button', { name: '推荐' })).toHaveStyle({
    borderColor: '#52c41a',
  })
  expect(screen.getByRole('button', { name: '不推荐' })).toHaveStyle({
    borderColor: '#ff4d4f',
  })
  expect(screen.getByRole('button', { name: '待定' })).toHaveStyle({
    borderColor: '#faad14',
  })
})
```

- [ ] **Step 2: Run the targeted test and verify RED**

Run:

```powershell
npm test -- src/pages/Public/Review.test.tsx
```

Expected: FAIL because only 推荐 currently has an explicit semantic border; 不推荐 and 待定 do not have the required red and yellow borders.

- [ ] **Step 3: Apply semantic styles to all three buttons**

Keep the existing recommendation values, icons, and click handlers. Use these exact style objects in `frontend/src/pages/Public/Review.tsx`:

```tsx
// 推荐
style={{
  backgroundColor: recommendation === 'recommend' ? '#52c41a' : undefined,
  borderColor: '#52c41a',
}}

// 不推荐
style={{
  backgroundColor: recommendation === 'not_recommend' ? '#ff4d4f' : undefined,
  borderColor: '#ff4d4f',
}}

// 待定
style={{
  backgroundColor: recommendation === 'pending' ? '#faad14' : undefined,
  borderColor: '#faad14',
  color: recommendation === 'pending' ? '#262626' : undefined,
}}
```

The dark selected text on the yellow button preserves contrast. Do not change the other page styling.

- [ ] **Step 4: Run the targeted test and verify GREEN**

Run:

```powershell
npm test -- src/pages/Public/Review.test.tsx
```

Expected: both tests PASS.

- [ ] **Step 5: Run proportional regression checks**

Run from `frontend/`:

```powershell
npm test
npm run build
```

Expected: all Vitest tests PASS and the TypeScript/Vite production build exits with code 0.

- [ ] **Step 6: Commit the button styling**

```powershell
git add -- frontend/src/pages/Public/Review.tsx frontend/src/pages/Public/Review.test.tsx
git commit -m "style: color public review recommendation borders"
```
