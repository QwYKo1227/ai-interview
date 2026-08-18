import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import request from '../../utils/request';
import RecruitmentPerformance from './index';

const authState = vi.hoisted(() => ({ role: 'hr' }));

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'hr-1', full_name: '招聘伙伴', role: authState.role } }),
}));

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));

const overview = {
  period: '2026-Q3',
  as_of: '2026-08-17',
  status: 'trial',
  people: [{
    user_id: 'hr-1',
    name: '招聘伙伴',
    email: 'hr@example.com',
    hc_count: 1,
    excluded_count: 0,
    onboarded_count: 0,
    task_points: 100,
    score: 60,
    achievement_rate: 0.6,
    positions: [{
      position_id: 'p-1', title: '后端工程师', category: 'domestic_rd', priority: 4,
      hc_count: 1, onboarded_count: 0, excluded_count: 0, task_points: 100,
      score: 60, achievement_rate: 0.6, highest_result_stage: '面试通过，进入录用决策', slots: [],
    }],
  }],
};

const mockRequests = (responseOverview = overview) => {
  vi.mocked(request.get).mockImplementation((url: string) => {
    if (url === '/recruitment-performance/periods') {
      return Promise.resolve({ periods: ['2026-Q2', '2026-Q3'], default_period: '2026-Q3' });
    }
    return Promise.resolve(responseOverview);
  });
};

describe('RecruitmentPerformance', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('shows an HR only their read-only position ledger', async () => {
    authState.role = 'hr';
    mockRequests();

    render(<RecruitmentPerformance />);

    expect(await screen.findByText('后端工程师')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '招聘绩效' })).toBeInTheDocument();
    expect(screen.getByText('按HC、岗位与负责人持有天数核算，季度内实时预估，结算后完整留痕。')).toBeInTheDocument();
    expect(screen.queryByText('RECRUITING PERFORMANCE LEDGER')).not.toBeInTheDocument();
    expect(screen.queryByText('试运行预览')).not.toBeInTheDocument();
    expect(screen.queryByText('每一分，都能回到一次真实交付')).not.toBeInTheDocument();
    expect(screen.getByText('数据截至 2026-08-17')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /规则设置/ })).not.toBeInTheDocument();
    await waitFor(() => expect(request.get).toHaveBeenCalledWith('/recruitment-performance/periods'));
    await waitFor(() => expect(request.get).toHaveBeenCalledWith(expect.stringContaining('/recruitment-performance/me?period=')));
  });

  it('shows admin overview and configuration navigation', async () => {
    authState.role = 'admin';
    mockRequests({
      ...overview,
      people: [
        overview.people[0],
        {
          ...overview.people[0],
          user_id: 'hr-2',
          name: '招聘伙伴二号',
          email: 'hr2@example.com',
          task_points: 300,
          score: 20,
          achievement_rate: 0.2,
          positions: [],
        },
      ],
    });

    render(<RecruitmentPerformance />);

    expect(await screen.findByText('招聘伙伴')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '人员概览' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /规则设置/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /季度结算/ })).toBeInTheDocument();
    const averageScore = screen.getByText('平均绩效得分').closest('.ant-statistic');
    const averageRate = screen.getByText('平均达成率').closest('.ant-statistic');
    expect(averageScore).toHaveTextContent('40.00');
    expect(averageRate).toHaveTextContent('40.00');
  });
});
