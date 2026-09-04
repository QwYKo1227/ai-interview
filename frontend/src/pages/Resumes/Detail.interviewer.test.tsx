import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import request from '../../utils/request';
import ResumeDetail from './Detail';

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'interviewer-1', role: 'interviewer' } }),
}));

vi.mock('../../hooks/useAuthenticatedFileUrl', () => ({
  useAuthenticatedFileUrl: () => ({ url: '', loading: false, error: null }),
}));

describe('ResumeDetail for a department reviewer', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders the selected review read-only without loading the aggregate', async () => {
    vi.mocked(request.get).mockResolvedValue({
      id: 'resume-1',
      candidate_name: '李四',
      status: 'pending_interview',
      parse_status: 'success',
      file_path: null,
      parsed_data: {},
      position: { id: 'position-new', title: '数据工程师' },
      department_reviews: [{
        id: 'review-1',
        reviewer_id: 'interviewer-1',
        reviewed_position_id: 'position-old',
        reviewed_position_title: '后端工程师',
        is_completed: true,
        technical_score: 8,
        experience_score: 9,
        overall_score: 9,
        recommendation: 'recommend',
        comment: '建议推进',
      }],
      hr_review: null,
    });

    render(
      <MemoryRouter initialEntries={['/resumes/resume-1?review_id=review-1']}>
        <Routes><Route path="/resumes/:id" element={<ResumeDetail />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText('我的部门评审')).toBeInTheDocument();
    expect(screen.getByText('候选人已转岗')).toBeInTheDocument();
    expect(screen.getByText('评审时岗位：后端工程师')).toBeInTheDocument();
    expect(screen.getByText('建议推进')).toBeInTheDocument();
    expect(screen.getByText('该评审已提交，仅支持查看')).toBeInTheDocument();
    await waitFor(() => {
      expect(request.get).toHaveBeenCalledWith('/resumes/resume-1?review_id=review-1');
    });
    expect(request.get).not.toHaveBeenCalledWith('/resumes/resume-1/department-reviews');
    expect(request.get).not.toHaveBeenCalledWith('/auth/interviewers');
  });
});
