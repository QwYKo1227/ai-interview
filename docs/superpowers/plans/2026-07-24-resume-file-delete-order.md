# Resume File Deletion Order Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make deletion of a resume with an attached stored file succeed without violating PostgreSQL foreign keys, while preserving linked coding tests.

**Architecture:** Keep one database transaction but split it into explicit phases. Delete or detach resume dependants and flush the resume deletion before staging stored-file metadata deletion; unlink physical files only after commit.

**Tech Stack:** Python 3.11, FastAPI service layer, SQLAlchemy 2.x, PostgreSQL 15, pytest

## Global Constraints

- Do not add a schema migration.
- Preserve linked coding tests by setting their nullable `resume_id` to `NULL`.
- Roll back every database metadata change on failure.
- Unlink physical files only after a successful database commit.

---

### Task 1: Resume deletion transaction ordering

**Files:**
- Modify: `backend/tests/test_tenant_file_storage.py:722`
- Modify: `backend/app/services/resume_service.py:440`

**Interfaces:**
- Consumes: `delete_resume(db: Session, resume_id: UUID)` and `stage_file_deletions(db, records)`.
- Produces: the same `delete_resume` interface, with ordered flush semantics and coding-test detachment.

- [x] **Step 1: Write the failing regression test**

Extend `test_delete_resume_revokes_download_and_unlinks_file` to enable SQLite foreign-key enforcement, create a linked `CodingTest`, and assert that deletion removes the resume and stored file while preserving the coding test:

```python
db.execute(text("PRAGMA foreign_keys=ON"))
coding_test = CodingTest(
    tenant_id=tenant_a.id,
    title="Preserved assessment",
    resume_id=test_resume.id,
)
db.add(coding_test)
db.commit()

resume_service.delete_resume(db, test_resume.id)

assert db.query(Resume).filter(Resume.id == test_resume.id).first() is None
assert db.query(StoredFile).filter(StoredFile.id == stored.id).first() is None
db.expire_all()
assert db.query(CodingTest).filter(CodingTest.id == coding_test.id).one().resume_id is None
assert not path.exists()
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `pytest -q tests/test_tenant_file_storage.py::test_delete_resume_revokes_download_and_unlinks_file`

Expected: FAIL with a foreign-key integrity error because either the stored file or resume is deleted before its referencing row is removed.

- [x] **Step 3: Implement the minimal ordered deletion**

Import `CodingTest`. Defer `stage_file_deletions`, detach coding tests, delete existing dependants and the resume, flush, then delete stored-file metadata and commit:

```python
db.query(CodingTest).filter(CodingTest.resume_id == resume_id).update(
    {CodingTest.resume_id: None}, synchronize_session=False
)
db.delete(db_resume)
try:
    db.flush()
    file_locations = stage_file_deletions(db, file_records)
    db.commit()
except Exception:
    db.rollback()
    raise
unlink_file_locations(file_locations, root=UPLOAD_ROOT)
```

- [x] **Step 4: Run the focused test and verify GREEN**

Run: `pytest -q tests/test_tenant_file_storage.py::test_delete_resume_revokes_download_and_unlinks_file`

Expected: `1 passed`.

- [x] **Step 5: Run relevant regression suites**

Run: `pytest -q tests/test_tenant_file_storage.py tests/test_tenant_route_isolation.py`

Expected: zero failures.

- [x] **Step 6: Run backend verification**

Run: `pytest -q`

Expected: zero failures. Then run `git diff --check` and inspect `git diff -- backend/app/services/resume_service.py backend/tests/test_tenant_file_storage.py`.

- [x] **Step 7: Commit the fix**

```bash
git add backend/app/services/resume_service.py backend/tests/test_tenant_file_storage.py docs/superpowers/plans/2026-07-24-resume-file-delete-order.md
git commit -m "fix: order resume file deletion safely"
```
