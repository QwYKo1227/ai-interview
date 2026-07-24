import { describe, expect, it } from 'vitest';
import { buildAuthenticatedResumeUpload } from './uploadRequest';

describe('authenticated resume upload', () => {
  it('uses the tenant-scoped batch endpoint for a single file', () => {
    const file = new Blob(['resume'], { type: 'application/pdf' });

    const request = buildAuthenticatedResumeUpload('position-1', [file]);

    expect(request.url).toBe('/resumes/batch');
    expect(request.formData.get('position_id')).toBe('position-1');
    const uploadedFiles = request.formData.getAll('files');
    expect(uploadedFiles).toHaveLength(1);
    expect(uploadedFiles[0]).toBeInstanceOf(Blob);
    expect((uploadedFiles[0] as Blob).size).toBe(file.size);
    expect(request.formData.has('file')).toBe(false);
  });
});
