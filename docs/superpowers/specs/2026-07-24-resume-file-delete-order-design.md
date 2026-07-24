# Resume File Deletion Order Fix

## Problem

Deleting a resume that has a `file_id` returns HTTP 500. The delete transaction currently stages the referenced `stored_files` row for deletion before deleting the `resumes` row. PostgreSQL may therefore issue the file-row delete first, and `fk_resumes_file_id_tenant` rejects it because the resume still references that row.

## Design

Keep the operation atomic at the database layer and perform it in two explicit phases:

1. Collect the file locations without deleting their metadata.
2. Delete or detach records that reference the resume. Preserve coding tests by setting their nullable `resume_id` to `NULL`.
3. Delete the resume and flush the session so PostgreSQL removes every reference to its file record.
4. Stage the `stored_files` rows for deletion and commit the transaction.
5. Only after a successful commit, unlink the physical files. If the transaction fails, roll it back and leave physical files intact.

No schema migration is required for this targeted fix.

## Error Handling

Any database failure rolls back all metadata changes and is re-raised. Physical files are deleted only after the database commit succeeds, retaining the existing best-effort cleanup behavior.

## Testing

Add a regression test using a database session with foreign-key enforcement enabled. It must create a resume whose `file_id` references a stored file, call `delete_resume`, and verify that both database records and the physical file are removed. The test must fail against the current ordering and pass after the fix.

Run the focused resume deletion tests, relevant tenant/file-storage tests, and the backend test suite available in the workspace.
