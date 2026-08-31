import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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

const leaderboard = {
  period: '2026-Q3',
  as_of: '2026-08-17',
  status: 'trial',
  entries: [
    { rank: 1, name: '王晓雯', achievement_rate: 1.268, is_current_user: false },
    { rank: 2, name: '李明', achievement_rate: 1.185, is_current_user: false },
    { rank: 3, name: '陈佳', achievement_rate: 1.092, is_current_user: false },
    { rank: 4, name: '招聘伙伴', achievement_rate: 0.6, is_current_user: true },
  ],
};

const mockRequests = (responseOverview = overview, responseLeaderboard = leaderboard) => {
  vi.mocked(request.get).mockImplementation((url: string) => {
    if (url === '/recruitment-performance/periods') {
      return Promise.resolve({ periods: ['2026-Q2', '2026-Q3'], default_period: '2026-Q3' });
    }
    if (url.startsWith('/recruitment-performance/leaderboard?')) {
      return Promise.resolve(responseLeaderboard);
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
    expect(screen.queryByText('按HC、岗位与负责人持有天数核算，季度内实时预估，结算后完整留痕。')).not.toBeInTheDocument();
    expect(screen.queryByText('RECRUITING PERFORMANCE LEDGER')).not.toBeInTheDocument();
    expect(screen.queryByText('试运行预览')).not.toBeInTheDocument();
    expect(screen.queryByText('每一分，都能回到一次真实交付')).not.toBeInTheDocument();
    expect(screen.getByText('数据截至 2026-08-17')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /规则设置/ })).not.toBeInTheDocument();
    await waitFor(() => expect(request.get).toHaveBeenCalledWith('/recruitment-performance/periods'));
    await waitFor(() => expect(request.get).toHaveBeenCalledWith(expect.stringContaining('/recruitment-performance/me?period=')));
    await waitFor(() => expect(request.get).toHaveBeenCalledWith(expect.stringContaining('/recruitment-performance/leaderboard?period=')));
  });

  it('shows a podium and the remaining minimal leaderboard in the hero', async () => {
    authState.role = 'hr';
    mockRequests();

    render(<RecruitmentPerformance />);

    await screen.findByText('王晓雯');
    const ranking = screen.getByRole('region', { name: '招聘绩效排行榜' });
    expect(within(ranking).getByText('王晓雯')).toBeInTheDocument();
    expect(within(ranking).getByText('126.80%')).toBeInTheDocument();
    expect(within(ranking).getByText('李明')).toBeInTheDocument();
    expect(within(ranking).getByText('陈佳')).toBeInTheDocument();
    expect(within(ranking).getByText('招聘伙伴').closest('.performance-rank-row')).toHaveAttribute('aria-current', 'true');
    expect(ranking.querySelectorAll('.performance-podium-entry')).toHaveLength(3);
    expect(ranking.querySelector('.performance-podium-avatar')).not.toBeInTheDocument();
  });

  it('renders reference-style medal svgs without current-user highlighting', async () => {
    authState.role = 'hr';
    mockRequests(overview, {
      ...leaderboard,
      entries: leaderboard.entries.map(entry => ({
        ...entry,
        is_current_user: entry.rank === 3,
      })),
    });

    render(<RecruitmentPerformance />);

    await screen.findByText('王晓雯');
    const ranking = screen.getByRole('region', { name: '招聘绩效排行榜' });
    const currentPodiumEntry = ranking.querySelector('.performance-podium-entry[aria-current="true"]');
    expect(currentPodiumEntry).toBeInTheDocument();
    expect(ranking.querySelector('.is-current-user')).not.toBeInTheDocument();
    expect(ranking.querySelectorAll('svg.performance-podium-medal')).toHaveLength(3);
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

    expect((await screen.findAllByText('招聘伙伴')).length).toBeGreaterThan(0);
    expect(screen.getByRole('tab', { name: '人员概览' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /规则设置/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /季度结算/ })).toBeInTheDocument();
    const averageScore = screen.getByText('平均绩效得分').closest('.ant-statistic');
    const averageRate = screen.getByText('平均达成率').closest('.ant-statistic');
    expect(averageScore).toHaveTextContent('40.00');
    expect(averageRate).toHaveTextContent('40.00');
  });

  it('does not display excluded markers or excluded HC rows', async () => {
    authState.role = 'hr';
    mockRequests({
      ...overview,
      people: [{
        ...overview.people[0],
        excluded_count: 1,
        positions: [{
          ...overview.people[0].positions[0],
          excluded_count: 1,
          slots: [
            {
              slot_id: 'slot-active', slot_number: 1, candidate_name: '正常候选人',
              result_stage: '岗位Open', result_coefficient: 0, target_days: 75,
              actual_days: 10, deducted_days: 0, effective_held_days: 10,
              time_coefficient: 1.2, task_points: 40, score: 0, status: 'active',
            },
            {
              slot_id: 'slot-cancelled', slot_number: 2, candidate_name: '被取消候选人',
              result_stage: '已剔除', result_coefficient: 0, target_days: 75,
              actual_days: 0, deducted_days: 0, effective_held_days: 0,
              time_coefficient: 0, task_points: 0, score: 0, status: 'cancelled',
            },
          ],
        }],
      }],
    });

    render(<RecruitmentPerformance />);

    await screen.findByText('后端工程师');
    expect(screen.queryByText(/剔除/)).not.toBeInTheDocument();
    const expandButton = document.querySelector<HTMLButtonElement>('.ant-table-row-expand-icon');
    expect(expandButton).not.toBeNull();
    fireEvent.click(expandButton!);
    expect(await screen.findByText('正常候选人')).toBeInTheDocument();
    expect(screen.queryByText('被取消候选人')).not.toBeInTheDocument();
    expect(screen.queryByText('已剔除')).not.toBeInTheDocument();
  });
});
