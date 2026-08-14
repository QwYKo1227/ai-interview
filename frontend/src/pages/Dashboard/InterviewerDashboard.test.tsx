import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import request from '../../utils/request';
import InterviewerDashboard from './InterviewerDashboard';

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'interviewer-1', full_name: '王评审', role: 'interviewer' } }),
}));

vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }));

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn() },
}));

describe('InterviewerDashboard', () => {
  it('shows only assignment-scoped work metrics and upcoming interviews', async () => {
    vi.mocked(request.get).mockResolvedValue({
      metrics: { pending_reviews: 3, today_interviews: 2, pending_feedback: 1 },
      upcoming_interviews: [{
        id: 'interview-1',
        candidate_name: '张三',
        position_title: '测试工程师',
        interview_time: '2026-08-11T07:00:00Z',
        interview_end_time: '2026-08-11T07:30:00Z',
        interview_type: 'video',
      }],
    });

    render(<InterviewerDashboard />);

    expect(await screen.findByText('你好，王评审')).toBeInTheDocument();
    expect(screen.getByText('待评审简历')).toBeInTheDocument();
    expect(screen.getByText('今日面试')).toBeInTheDocument();
    expect(screen.getByText('待提交评价')).toBeInTheDocument();
    expect(screen.getByText('张三')).toBeInTheDocument();
    expect(screen.getByText('测试工程师')).toBeInTheDocument();
    expect(screen.queryByText('招聘漏斗')).not.toBeInTheDocument();
    await waitFor(() => expect(request.get).toHaveBeenCalledWith('/dashboard/interviewer'));
    expect(request.get).toHaveBeenCalledTimes(1);
  });
});
