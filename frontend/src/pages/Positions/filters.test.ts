import { describe, expect, it } from 'vitest';
import { buildPositionListParams } from './filters';

describe('buildPositionListParams', () => {
  it('omits hiring_manager_id when no manager is selected', () => {
    expect(buildPositionListParams({ title: '', status: undefined, hiringManagerId: undefined }))
      .toEqual({ title: '', status: undefined });
  });

  it('combines hiring manager with title and status', () => {
    expect(buildPositionListParams({
      title: 'Backend',
      status: 'published',
      hiringManagerId: 'manager-id',
    })).toEqual({
      title: 'Backend',
      status: 'published',
      hiring_manager_id: 'manager-id',
    });
  });
});
