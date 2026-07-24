# Public Department Review Resume Preview Design

## Context

The public department review page currently exposes parsed resume text, candidate information, AI screening notes, and the review form, but it does not provide access to the original uploaded resume. Internal resume detail pages already preview PDF files and offer download-only fallback for unsupported formats. Public reviewers cannot reuse the authenticated file endpoint because they are not required to have an application session.

The existing department review token expires 14 days after it is issued and is revoked immediately after submission. The requested experience also requires reopening the same link after submission to show a completed-review receipt rather than a not-found error.

## Goals

- Show the original resume beside the public review form on desktop and above it on narrow screens.
- Preview PDF files inline and offer a download action for every available file.
- Keep public file access scoped to the department review token without exposing internal paths.
- Let the same review link show a minimal completed-review receipt after submission and before its original 14-day expiry.
- Prevent completed links from exposing candidate data, resume files, or another submission attempt.

## Non-goals

- Adding online rendering for Word, image, or other non-PDF resume formats.
- Changing the 14-day department review link lifetime.
- Making resume files generally public or reusable outside a specific department review link.
- Redesigning internal resume-management pages.

## Page Layout

The active public review page uses a two-pane layout on desktop:

- Left pane: “简历原件预览”, inline PDF viewer, and “下载原件”.
- Right pane: candidate information, AI screening notes, parsed resume text, and the existing review form.

On narrow screens the panes stack vertically, with the original resume before the review content. The preview has a bounded responsive height so the page remains usable without forcing the entire document into the viewport.

For PDF content, the frontend creates a browser object URL and uses the existing maximized PDF preview helper. For all other content types, the pane states that online preview is unsupported and provides “下载原件”. Missing files and load failures produce a local preview message without hiding or disabling the review form.

## Public API and Security

### Active Review Payload

`GET /api/public/review/{token}` continues to resolve the opaque department review token and enforce the request tenant. For an incomplete review it returns the existing candidate and review payload plus only the metadata needed to determine whether an original file is available. It does not return a storage path.

### Review-Scoped File Endpoint

`GET /api/public/review/{token}/resume-file` resolves the department review token, enforces the tenant, requires the review to be incomplete, and verifies that the stored file belongs to the review's resume. It streams the stored file through the existing safe file-response behavior. A missing, mismatched, completed, expired, or otherwise invalid resource returns a non-disclosing public error.

The frontend requests this endpoint as a Blob, derives the content type from the response, creates an object URL, and revokes the URL when the token changes or the component unmounts.

### Receipt-Only Completed State

Submitting a review atomically marks the review complete but does not revoke its public token. Until the token's original expiry, the token becomes receipt-only:

- The review GET endpoint returns only a completed-state response.
- The resume-file endpoint rejects access.
- The submit endpoint rejects a repeated submission.
- Candidate information, parsed content, AI notes, and file metadata are not returned.

At or after the recorded `expires_at`, the link returns the existing expired-link response. Resume deletion, tenant deactivation, token replacement, or other existing invalidation rules may make a link unavailable earlier.

## Completed and Error States

Both an immediately successful submission and reopening a receipt-only link render the same page:

- Title: “审核已完成”
- Confirmation text that the review was submitted
- Button: “返回简历管理”, linking to `/resumes`

If the viewer is not authenticated, existing protected-route behavior handles the transition to login. Expired links show an explicit expired-link state. Invalid or unavailable links retain a non-disclosing not-found state.

## Data Flow

1. The public page requests the review payload with the review token.
2. If the review is incomplete, the page renders the two-pane review layout.
3. If an original file is available, the frontend requests the review-scoped file endpoint and creates a temporary object URL.
4. The reviewer submits the form; the backend marks the review complete while leaving the token valid until its original expiry.
5. The frontend immediately renders the completed receipt without refetching.
6. A later GET with the same unexpired token returns only the completed receipt state.

## Testing

Backend tests cover:

- An incomplete review token can download only the stored file linked to its own resume.
- Cross-tenant, mismatched, missing, expired, and invalid file access is rejected.
- Completed reviews return only receipt state and cannot access the file or submit again.
- The receipt remains available until the existing 14-day expiry and expires normally afterward.

Frontend tests cover:

- Active review payloads render a desktop two-pane structure that stacks at the responsive breakpoint.
- PDF blobs render in the inline preview and expose a download action.
- Non-PDF blobs show the unsupported-preview fallback and expose a download action.
- Missing or failed file loads do not prevent form use.
- A successful submit and a reopened completed link render the same completed page.
- “返回简历管理” targets `/resumes`.
