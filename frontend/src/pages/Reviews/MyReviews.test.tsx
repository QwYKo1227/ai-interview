import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import request from '../../utils/request';
import MyReviews from './MyReviews';

const navigate = vi.fn();

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'interviewer-1', role: 'interviewer' } }),
}));

vi.mock('react-router-dom', () => ({
  useNavigate: () => navigate,
}));

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn() },
}));

describe('MyReviews', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('switches from pending assignments to searchable completed history', async () => {
    const user = userEvent.setup();
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      const completed = url.includes('completed=true');
      return {
        items: completed ? [{
          review_id: 'review-completed',
          resume_id: 'resume-2',
          candidate_name: '李四',
          position_title: '后端工程师',
          status: 'pending_interview',
          is_completed: true,
          overall_score: 9,
          recommendation: 'recommend',
          created_at: '2026-08-01T00:00:00Z',
          completed_at: '2026-08-02T00:00:00Z',
        }] : [{
          review_id: 'review-pending',
          resume_id: 'resume-1',
          candidate_name: '张三',
          position_title: '测试工程师',
          match_score: 80,
          status: 'pending_dept_review',
          is_completed: false,
          created_at: '2026-08-03T00:00:00Z',
        }],
        total: 1,
        pending_total: 1,
        completed_total: 1,
        page: 1,
        page_size: 10,
        total_pages: 1,
      };
    });

    render(<MyReviews />);

    expect(await screen.findByText('张三')).toBeInTheDocument();
    expect(screen.getByText('待我评审 (1)')).toBeInTheDocument();
    await user.click(screen.getByText('我已评审 (1)'));

    expect(await screen.findByText('李四')).toBeInTheDocument();
    expect(screen.getByText('推荐')).toBeInTheDocument();
    expect(screen.getByText('9/10')).toBeInTheDocument();

    const search = screen.getByPlaceholderText('搜索候选人或岗位');
    await user.type(search, '后端{enter}');
    await waitFor(() => {
      expect(request.get).toHaveBeenLastCalledWith(
        expect.stringContaining('search=%E5%90%8E%E7%AB%AF'),
      );
    });

    await user.click(screen.getByRole('button', { name: /查看/ }));
    expect(navigate).toHaveBeenCalledWith(
      '/resumes/resume-2?review_id=review-completed',
      { state: { returnTo: expect.stringContaining('tab=completed') } },
    );
  }, 15000);
});
