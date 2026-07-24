# Public Department Review Resume Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add secure original-resume preview and download to the public department review page, while allowing an unexpired completed link to show only a completed-review receipt.

**Architecture:** Keep the opaque department review token as the sole public capability. Active tokens may load the review payload and a new review-scoped file endpoint; completed tokens remain resolvable only for a minimal receipt until their original 14-day expiry, while file access and repeat submission are denied. The React page fetches the file as a Blob, creates a temporary object URL, and renders a responsive two-pane PDF preview with download fallback.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, React 19, TypeScript, Ant Design 6, React Router 7, Vitest 4, Testing Library

## Global Constraints

- Keep the department review link lifetime at 14 days from issuance.
- Do not expose `Resume.file_path`, `StoredFile.object_key`, or a reusable stored-file public token.
- Completed review links may return only receipt state; they may not return candidate data, AI notes, parsed resume content, file metadata, or file bytes.
- PDF files preview inline; Word, image, and other formats use download-only fallback.
- The desktop page uses left preview and right review content; narrow screens stack preview above content.
- Missing or failed file loads must not prevent the reviewer from using the review form.

---

## File Structure

- Modify `backend/app/services/resume_service.py`: return active versus receipt-only payloads, preserve the review token after submission, and resolve the tenant-bound review file.
- Modify `backend/app/routes/public_review.py`: add the review-scoped resume-file route and enforce completed/file ownership checks.
- Modify `backend/tests/test_public_token_tenant_isolation.py`: backend regression coverage for receipt-only links and review-scoped file access.
- Modify `frontend/src/hooks/useAuthenticatedFileUrl.ts`: expose additive loading and error state for Blob fetches.
- Modify `frontend/src/pages/Public/Review.tsx`: render completed/expired states, load the review-scoped file, and build the two-pane preview UI.
- Modify `frontend/src/pages/Public/Review.test.tsx`: frontend behavior coverage.
- Modify `frontend/src/index.css`: responsive public review layout.

### Task 1: Preserve an Unexpired Token as a Completed Receipt

**Files:**
- Modify: `backend/tests/test_public_token_tenant_isolation.py`
- Modify: `backend/app/services/resume_service.py`

**Interfaces:**
- Consumes: `resolve_public_token(db, raw, "department_review")` and `DepartmentReview.is_completed`.
- Produces: `get_public_review_payload(...) -> {"completed": True}` for completed reviews; active payloads include `completed: False` and `resume.file_available: bool`.

- [ ] **Step 1: Extend the public review route test to require receipt-only reopening**

Update `test_review_public_route_uses_precreated_review_token_not_reviewer_query` so the assertions after the successful submit are:

```python
    submitted = client.post(
        f"/api/public/review/{raw}/submit",
        json={"technical_score": 8, "overall_score": 8, "recommendation": "recommend", "comment": "ok"},
    )
    assert submitted.status_code == 200

    reopened = client.get(f"/api/public/review/{raw}")
    assert reopened.status_code == 200
    assert reopened.json() == {"completed": True}

    repeated = client.post(
        f"/api/public/review/{raw}/submit",
        json={"technical_score": 9, "overall_score": 9, "recommendation": "recommend"},
    )
    assert repeated.status_code == 404
    token_record = db.query(PublicAccessToken).filter(
        PublicAccessToken.token_hash == hash_token(raw)
    ).one()
    assert token_record.revoked_at is None

    token_record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    expired = client.get(f"/api/public/review/{raw}")
    assert expired.status_code == 410
```

Also add these assertions immediately after the first active GET:

```python
    assert response.json()["completed"] is False
    assert response.json()["resume"]["file_available"] is False
```

- [ ] **Step 2: Run the backend test and verify RED**

Run from `backend/`:

```powershell
python -m pytest tests/test_public_token_tenant_isolation.py::test_review_public_route_uses_precreated_review_token_not_reviewer_query -q
```

Expected: FAIL because submission revokes the token, reopening returns 404, and the active payload lacks `completed` and `file_available`.

- [ ] **Step 3: Implement active and receipt-only payloads**

At the start of `get_public_review_payload` in `backend/app/services/resume_service.py`, add:

```python
    if review.is_completed:
        return {"completed": True}
```

Add `completed` to the active return object and `file_available` to the nested resume object:

```python
    return {
        "completed": False,
        "resume": {
            # existing safe resume fields remain unchanged
            "file_available": resume.file_id is not None,
        },
        "existing_review": {
            # existing review fields remain unchanged
        },
    }
```

In `submit_public_department_review`, delete only this call:

```python
    revoke_public_tokens(db, tenant_id, "department_review", review_id)
```

Then remove `revoke_public_tokens` from the import if it is unused elsewhere in that module. Keep the atomic `is_completed.is_(False)` update unchanged so repeat submissions still return 404.

- [ ] **Step 4: Run the backend test and verify GREEN**

Run:

```powershell
python -m pytest tests/test_public_token_tenant_isolation.py::test_review_public_route_uses_precreated_review_token_not_reviewer_query -q
```

Expected: PASS.

- [ ] **Step 5: Commit the receipt lifecycle**

```powershell
git add -- backend/app/services/resume_service.py backend/tests/test_public_token_tenant_isolation.py
git commit -m "feat: keep completed review links receipt-only"
```

### Task 2: Add the Review-Scoped Resume File Endpoint

**Files:**
- Modify: `backend/tests/test_public_token_tenant_isolation.py`
- Modify: `backend/app/routes/public_review.py`
- Modify: `backend/app/services/resume_service.py`

**Interfaces:**
- Consumes: active `DepartmentReview`, its tenant-bound `Resume.file_id`, and `_response(record)` from `backend/app/routes/files.py` for safe streaming headers and MIME sanitization.
- Produces: `get_public_review_file(db, review) -> StoredFile` and `GET /api/public/review/{token}/resume-file`.

- [ ] **Step 1: Add failing active/completed and ownership tests**

Add these imports to `backend/tests/test_public_token_tenant_isolation.py`:

```python
from io import BytesIO
from fastapi import UploadFile
from app.routes import files
from app.utils.file_storage import save_upload_file
```

Add this test:

```python
def test_review_resume_file_is_available_only_while_review_is_active(
    db, tenant_a, test_resume, test_user, tmp_path
):
    stored = save_upload_file(
        UploadFile(filename="candidate.pdf", file=BytesIO(b"resume-pdf")),
        tenant_a.id,
        "resumes",
        root=tmp_path,
        resource_type="resume",
        resource_id=test_resume.id,
    )
    db.add(stored)
    db.flush()
    test_resume.file_id = stored.id
    review = DepartmentReview(
        tenant_id=tenant_a.id,
        resume_id=test_resume.id,
        reviewer_id=test_user.id,
        is_completed=False,
    )
    db.add(review)
    db.commit()
    raw = issue_public_token(
        db, tenant_a.id, "department_review", review.id,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    files.UPLOAD_ROOT = tmp_path
    client = _client(db, public_review.router)

    active = client.get(f"/api/public/review/{raw}/resume-file")
    assert active.status_code == 200
    assert active.content == b"resume-pdf"
    assert active.headers["content-type"] == "application/pdf"

    submitted = client.post(
        f"/api/public/review/{raw}/submit",
        json={"recommendation": "recommend"},
    )
    assert submitted.status_code == 200
    blocked = client.get(f"/api/public/review/{raw}/resume-file")
    assert blocked.status_code == 404
```

Add the ownership-negative test:

```python
def test_review_resume_file_rejects_mismatched_stored_file(
    db, tenant_a, test_resume, test_user, tmp_path
):
    stored = save_upload_file(
        UploadFile(filename="other.pdf", file=BytesIO(b"other")),
        tenant_a.id,
        "resumes",
        root=tmp_path,
        resource_type="resume",
        resource_id=uuid4(),
    )
    db.add(stored)
    db.flush()
    test_resume.file_id = stored.id
    review = DepartmentReview(
        tenant_id=tenant_a.id, resume_id=test_resume.id,
        reviewer_id=test_user.id, is_completed=False,
    )
    db.add(review)
    db.commit()
    raw = issue_public_token(
        db, tenant_a.id, "department_review", review.id,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    files.UPLOAD_ROOT = tmp_path
    client = _client(db, public_review.router)

    response = client.get(f"/api/public/review/{raw}/resume-file")
    assert response.status_code == 404
    assert response.json()["detail"] == "Public resource not found"
```

- [ ] **Step 2: Run the new endpoint tests and verify RED**

Run:

```powershell
python -m pytest tests/test_public_token_tenant_isolation.py -k "review_resume_file" -q
```

Expected: both tests FAIL with 404 because the route does not exist.

- [ ] **Step 3: Implement strict stored-file resolution and streaming**

Add this service function to `backend/app/services/resume_service.py`:

```python
def get_public_review_file(db: Session, review: DepartmentReview) -> StoredFile:
    if review.is_completed:
        raise HTTPException(status_code=404, detail="Public resource not found")
    resume = db.query(Resume).filter(
        Resume.id == review.resume_id,
        Resume.tenant_id == review.tenant_id,
    ).first()
    if resume is None or resume.file_id is None:
        raise HTTPException(status_code=404, detail="Public resource not found")
    record = db.query(StoredFile).filter(
        StoredFile.id == resume.file_id,
        StoredFile.tenant_id == review.tenant_id,
        StoredFile.resource_type == "resume",
        StoredFile.resource_id == resume.id,
    ).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Public resource not found")
    return record
```

Add these imports to `backend/app/routes/public_review.py`:

```python
from app.routes.files import _response as stored_file_response
from app.services.resume_service import get_public_review_file
```

Add this route:

```python
@router.get("/{token}/resume-file")
def get_resume_file_for_review(
    token: str,
    request: Request,
    db: Session = Depends(get_unscoped_db),
):
    review = _resolve_review(db, token, request)
    record = get_public_review_file(db, review)
    return stored_file_response(record)
```

Keeping the business queries in the service also preserves the existing guard that public route modules do not query `Resume` through an unscoped session. Do not return `record.object_key`, `resume.file_path`, or a separate public file token.

- [ ] **Step 4: Run the endpoint and public-token suites**

Run:

```powershell
python -m pytest tests/test_public_token_tenant_isolation.py tests/test_tenant_file_storage.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the secure file endpoint**

```powershell
git add -- backend/app/routes/public_review.py backend/app/services/resume_service.py backend/tests/test_public_token_tenant_isolation.py
git commit -m "feat: stream resume through public review token"
```

### Task 3: Render Completed and Expired Public Review States

**Files:**
- Modify: `frontend/src/pages/Public/Review.test.tsx`
- Modify: `frontend/src/pages/Public/Review.tsx`

**Interfaces:**
- Consumes: active payload `{ completed: false, resume, existing_review }`, completed payload `{ completed: true }`, and HTTP 410 errors.
- Produces: a unified “审核已完成” receipt with a “返回简历管理” navigation button, plus an explicit expired-link result.

- [ ] **Step 1: Add failing completed-link and expiry tests**

Add `completed: false` to the shared `reviewPayload` fixture in `frontend/src/pages/Public/Review.test.tsx`.

Extend `renderReview` with the destination route:

```tsx
const renderReview = () => render(
  <MemoryRouter initialEntries={['/public/review/public-token']}>
    <Routes>
      <Route path="/public/review/:token" element={<PublicReview />} />
      <Route path="/resumes" element={<div>简历管理模块</div>} />
    </Routes>
  </MemoryRouter>,
)
```

Add these tests:

```tsx
it('renders the same completed receipt when an unexpired link is reopened', async () => {
  vi.mocked(request.get).mockResolvedValueOnce({ completed: true })
  renderReview()

  await screen.findByText('审核已完成')
  fireEvent.click(screen.getByRole('button', { name: '返回简历管理' }))
  expect(await screen.findByText('简历管理模块')).toBeInTheDocument()
  expect(request.get).toHaveBeenCalledWith('/public/review/public-token')
})

it('shows an explicit expired-link result for HTTP 410', async () => {
  vi.mocked(request.get).mockRejectedValueOnce({ response: { status: 410 } })
  renderReview()

  expect(await screen.findByText('评审链接已过期')).toBeInTheDocument()
  expect(screen.queryByText('简历审核')).not.toBeInTheDocument()
})
```

Update the existing successful-submit test to click “返回简历管理” after “审核已完成” appears and assert the destination route renders.

- [ ] **Step 2: Run the public review frontend tests and verify RED**

Run from `frontend/`:

```powershell
npm test -- src/pages/Public/Review.test.tsx
```

Expected: FAIL because `{ completed: true }` currently falls into the missing-resume state, HTTP 410 is not distinguished, and the receipt button still says “返回首页”.

- [ ] **Step 3: Implement explicit page states and navigation**

In `frontend/src/pages/Public/Review.tsx`, add:

```tsx
type LoadError = 'expired' | 'not_found' | null

const [completed, setCompleted] = useState(false)
const [loadError, setLoadError] = useState<LoadError>(null)
```

At the start of `fetchResume`, reset the error and handle completed payloads before reading `resume`:

```tsx
      setLoadError(null)
      const res = await request.get(`/public/review/${token}`)
      if (res.completed) {
        setCompleted(true)
        setResume(null)
        return
      }
      setCompleted(false)
      setResume(res.resume)
```

Replace the fetch catch body with:

```tsx
      setLoadError(e?.response?.status === 410 ? 'expired' : 'not_found')
      setResume(null)
```

After successful submission, call `setCompleted(true)` instead of mutating `existingReview`. Render states in this order: loading, expired, completed, missing resume, active review.

Use this expired state:

```tsx
<Result
  status="warning"
  title="评审链接已过期"
  subTitle="该链接已超过 14 天有效期，请联系招聘负责人。"
/>
```

Use this unified receipt action:

```tsx
<Button type="primary" key="resumes" onClick={() => navigate('/resumes')}>
  返回简历管理
</Button>
```

- [ ] **Step 4: Run the public review frontend tests and verify GREEN**

Run:

```powershell
npm test -- src/pages/Public/Review.test.tsx
```

Expected: all tests PASS.

- [ ] **Step 5: Commit the completed and expired states**

```powershell
git add -- frontend/src/pages/Public/Review.tsx frontend/src/pages/Public/Review.test.tsx
git commit -m "feat: show public review receipt and expiry states"
```

### Task 4: Add Blob Preview, Download Fallback, and Responsive Layout

**Files:**
- Modify: `frontend/src/hooks/useAuthenticatedFileUrl.ts`
- Modify: `frontend/src/pages/Public/Review.tsx`
- Modify: `frontend/src/pages/Public/Review.test.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: `resume.file_available`, `/public/review/{token}/resume-file`, Blob MIME type, and `getMaximizedPdfPreviewUrl(fileUrl)`.
- Produces: `{ url, contentType, loading, error }` from `useAuthenticatedFileUrl`; `.public-review-layout`, `.public-review-preview`, and `.public-review-content` layout hooks.

- [ ] **Step 1: Add failing PDF, fallback, failure, and layout tests**

Add `file_available: true` to the shared resume fixture. Import the stylesheet:

```tsx
import publicReviewCss from '../../index.css?inline'
```

In `beforeEach`, define deterministic object URL methods and make the request mock route-aware:

```tsx
Object.defineProperty(URL, 'createObjectURL', {
  configurable: true,
  value: vi.fn(() => 'blob:resume-preview'),
})
Object.defineProperty(URL, 'revokeObjectURL', {
  configurable: true,
  value: vi.fn(),
})
vi.mocked(request.get).mockReset().mockImplementation(async (url: string) => {
  if (url === '/public/review/public-token') return reviewPayload
  if (url === '/public/review/public-token/resume-file') {
    return new Blob([btoa('pdf')], { type: 'application/pdf' })
  }
  throw new Error(`Unexpected GET ${url}`)
})
```

Add these tests:

```tsx
it('renders a PDF preview and download action in the left pane', async () => {
  const { container } = renderReview()

  await screen.findByText('测试候选人')
  const layout = container.querySelector('.public-review-layout')
  expect(layout).toBeInTheDocument()
  expect(layout?.firstElementChild).toHaveClass('public-review-preview')
  expect(container.querySelector('iframe[title="Resume Preview"]')).toHaveAttribute(
    'src', expect.stringContaining('blob:resume-preview'),
  )
  expect(screen.getByRole('link', { name: /下载原件/ })).toHaveAttribute(
    'href', 'blob:resume-preview',
  )
  expect(publicReviewCss).toMatch(/\.public-review-layout\s*{[^}]*display:\s*flex;/s)
  expect(publicReviewCss).toMatch(/@media\s*\(max-width:\s*900px\)[\s\S]*\.public-review-layout\s*{[^}]*flex-direction:\s*column;/)
})

it('uses download-only fallback for a non-PDF resume', async () => {
  vi.mocked(request.get).mockImplementation(async (url: string) => {
    if (url === '/public/review/public-token') return reviewPayload
    return new Blob(['docx'], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    })
  })
  renderReview()

  expect(await screen.findByText('该文件格式暂不支持在线预览，请下载后查看')).toBeInTheDocument()
  expect(screen.queryByTitle('Resume Preview')).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: /下载原件/ })).toBeInTheDocument()
})

it('keeps the review form usable when the original file fails to load', async () => {
  vi.mocked(request.get).mockImplementation(async (url: string) => {
    if (url === '/public/review/public-token') return reviewPayload
    throw new Error('file unavailable')
  })
  renderReview()

  expect(await screen.findByText('简历原件加载失败')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '提交审核' })).toBeEnabled()
})
```

- [ ] **Step 2: Run the frontend test and verify RED**

Run:

```powershell
npm test -- src/pages/Public/Review.test.tsx
```

Expected: FAIL because the page does not request the resume file, render the preview, or expose the responsive layout classes.

- [ ] **Step 3: Add loading/error output to the Blob URL hook**

In `frontend/src/hooks/useAuthenticatedFileUrl.ts`, add state and return fields without removing `url` or `contentType`:

```tsx
const [loading, setLoading] = useState(false)
const [error, setError] = useState(false)
```

Reset them at the start of the effect, set `loading` only when `path` exists, clear it after success/failure, and set `error` only for a non-aborted failure:

```tsx
setLoading(Boolean(path))
setError(false)
// success
setLoading(false)
// catch, when not aborted
setError(true)
setLoading(false)
```

Return:

```tsx
return { url, contentType, loading, error }
```

- [ ] **Step 4: Build the preview pane and active two-pane layout**

In `frontend/src/pages/Public/Review.tsx`:

```tsx
import { DownloadOutlined, FileWordOutlined } from '@ant-design/icons'
import { getMaximizedPdfPreviewUrl } from '../../utils/pdfPreview'
import { useAuthenticatedFileUrl } from '../../hooks/useAuthenticatedFileUrl'
```

Add `file_available: boolean` to `ResumeData`. Derive the review-scoped path and preview state before the early returns:

```tsx
const resumeFile = useAuthenticatedFileUrl(
  resume?.file_available && token
    ? `/api/public/review/${token}/resume-file`
    : undefined,
)
const isPdf = resumeFile.contentType === 'application/pdf'
const pdfPreviewUrl = isPdf ? getMaximizedPdfPreviewUrl(resumeFile.url) : ''
```

Keep hooks above all conditional returns. Wrap the active page in:

```tsx
<div className="public-review-page">
  <div className="public-review-layout">
    <section className="public-review-preview" aria-label="简历原件预览">
      {/* preview header, PDF iframe, fallback, loading, error, or unavailable state */}
    </section>
    <main className="public-review-content">
      {/* existing Card and review content */}
    </main>
  </div>
</div>
```

The preview header always shows “简历原件预览”. When `resumeFile.url` exists, render a “下载原件” anchor-style Ant button with `href={resumeFile.url}`, `download`, and `DownloadOutlined`. Render the PDF iframe only when `isPdf`; otherwise render the exact fallback string from the test with `FileWordOutlined`. Render “加载预览中...” while loading, “简历原件加载失败” on error, and “暂无简历原件” when `file_available` is false.

- [ ] **Step 5: Add exact responsive styles**

Append to `frontend/src/index.css`:

```css
.public-review-page {
  padding: 32px;
  max-width: 1500px;
  margin: 0 auto;
}

.public-review-layout {
  display: flex;
  align-items: flex-start;
  gap: 24px;
  min-width: 0;
}

.public-review-preview,
.public-review-content {
  flex: 1 1 0;
  min-width: 0;
}

.public-review-preview {
  position: sticky;
  top: 24px;
  height: calc(100vh - 48px);
  min-height: 560px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  background: #f1f5f9;
}

@media (max-width: 900px) {
  .public-review-page {
    padding: 16px;
  }

  .public-review-layout {
    flex-direction: column;
  }

  .public-review-preview,
  .public-review-content {
    width: 100%;
  }

  .public-review-preview {
    position: static;
    height: 70vh;
    min-height: 480px;
  }
}
```

Use inline styles inside the preview only for its header/body substructure; keep layout and responsive behavior in these classes.

- [ ] **Step 6: Run targeted frontend tests and verify GREEN**

Run:

```powershell
npm test -- src/pages/Public/Review.test.tsx src/pages/Resumes/Detail.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Run full proportional verification**

Run:

```powershell
cd backend
python -m pytest tests/test_public_token_tenant_isolation.py tests/test_tenant_file_storage.py -q
cd ..\frontend
npm test -- --testTimeout=10000
npm run build
```

Expected: backend suites PASS, all Vitest tests PASS, and the TypeScript/Vite build exits with code 0. The existing Vite large-chunk warning is non-blocking.

- [ ] **Step 8: Commit the preview UI**

```powershell
git add -- frontend/src/hooks/useAuthenticatedFileUrl.ts frontend/src/pages/Public/Review.tsx frontend/src/pages/Public/Review.test.tsx frontend/src/index.css
git commit -m "feat: preview resume in public department review"
```
