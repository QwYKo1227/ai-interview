import { describe, expect, it } from 'vitest';
import {
  buildAuthenticatedResumeUpload,
  getResumeFileValidationError,
  MAX_RESUME_FILE_SIZE_BYTES,
} from './uploadRequest';

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

  it('accepts a PDF at the 10 MB limit', () => {
    const file = {
      name: 'candidate.pdf',
      size: MAX_RESUME_FILE_SIZE_BYTES,
      type: 'application/pdf',
    };

    expect(getResumeFileValidationError(file)).toBeNull();
  });

  it('rejects a resume larger than 10 MB with a user-facing message', () => {
    const file = {
      name: 'candidate.pdf',
      size: MAX_RESUME_FILE_SIZE_BYTES + 1,
      type: 'application/pdf',
    };

    expect(getResumeFileValidationError(file)).toBe(
      '单个简历文件不能超过 10 MB',
    );
  });

  it('does not build a request containing an oversized file', () => {
    const file = {
      size: MAX_RESUME_FILE_SIZE_BYTES + 1,
    } as Blob;

    expect(() =>
      buildAuthenticatedResumeUpload('position-1', [file]),
    ).toThrow('单个简历文件不能超过 10 MB');
  });
});
