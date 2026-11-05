import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import request from '../../utils/request';
import RecruitmentQuality from './index';
import type { Report } from './types';

const mocks = vi.hoisted(() => ({ navigate: vi.fn(), role: 'admin' }));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'hr', role: mocks.role } }) }));
vi.mock('react-router-dom', () => ({ useNavigate: () => mocks.navigate }));
vi.mock('../../utils/request', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
const metrics = {
  completed_nodes: 2, required_nodes: 3, process_rate: 66.7,
  overdue_count: 1, missing_count: 1, unknown_count: 0, historical_count: 0, longest_overdue_hours: 12,
};
const report: Report = {
  enabled: true, as_of: '2026-11-03T08:00:00Z', rollout_at: '2026-11-01T00:00:00Z', summary: metrics,
  people: [{ user_id: 'hr', name: '招聘甲', position_count: 1, candidate_count: 1, open_position_count: 1, active_candidate_count: 1, ...metrics }],
  positions: [{ id: 'position', title: '后端工程师' }],
  nodes: [{ id: 'binding/review:panel', binding_id: 'binding', key: 'review:panel', position_id: 'position', position_title: '后端工程师',
    resume_id: 'resume', candidate_name: '张三', owner_id: 'hr', owner_name: '招聘甲', executor_id: 'interviewer', executor_name: '面试官乙',
    stage: 'interview', label: '第1轮面试评价', status: 'missing', eligible: true, complete: false, historical: false,
    fields: [{ label: '人工评价', valid: false }], missing: ['人工评价'], due_at: '2026-11-02T20:00:00Z', paused: false, overdue: true, overdue_hours: 12,
    href: '/interviews/interview/score', policy_id: 'policy', policy_name: '标准流程', policy_version: 1, evidence: [], actions: [] }],
};
const settings = { enabled: true, defaults: {
  screening_days: 2, department_assignment_days: 2, department_decision_days: 1, interview_arrangement_days: 2,
  next_interview_days: 2, interview_decision_days: 1, offer_send_days: 2, result_update_days: 1,
  exception_days: 1, department_review_required: false,
}, policies: [] };

describe('RecruitmentQuality', () => {
  beforeEach(() => {
    mocks.role = 'admin';
    vi.mocked(request.get).mockImplementation(async (url: string) => url.endsWith('/config') ? settings : report);
    vi.mocked(request.post).mockResolvedValue({ id: 'action' });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks(); });

  it('requests and clears a custom date range without a record scope dropdown', async () => {
    const user = userEvent.setup();
    render(<RecruitmentQuality />);
    const start = await screen.findByPlaceholderText('开始日期');
    const end = screen.getByPlaceholderText('结束日期');
    await user.click(start);
    await user.type(start, '2026-11-01{Enter}');
    await user.click(end);
    await user.type(end, '2026-11-04{Enter}');
    await waitFor(() => expect(request.get).toHaveBeenCalledWith('/recruitment-quality/overview', {
      params: { start_date: '2026-11-01', end_date: '2026-11-04' },
    }));
    expect(screen.queryByRole('combobox', { name: '记录范围' })).not.toBeInTheDocument();
    await user.click(start.closest('.ant-picker')!.querySelector('.ant-picker-clear')!);
    await waitFor(() => expect(vi.mocked(request.get).mock.calls.filter(([url]) => url.endsWith('/overview')).at(-1)).toEqual([
      '/recruitment-quality/overview', { params: {} },
    ]));
  }, 15000);

  it('shows real denominators and separates owner from the assigned executor', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    const user = userEvent.setup();
    render(<RecruitmentQuality />);
    expect(await screen.findByText('张三')).toBeInTheDocument();
    expect(screen.getAllByText('2 / 3').length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: /一面.*查看依据/ }));
    const drawer = await screen.findByRole('dialog');
    expect(within(drawer).getByText('当前待办执行人')).toBeInTheDocument();
    expect(within(drawer).getByText('面试官乙')).toBeInTheDocument();
    await user.click(within(drawer).getByRole('button', { name: '进入业务页面处理' }));
    expect(open).toHaveBeenCalledWith('/interviews/interview/score', '_blank', 'noopener,noreferrer');
    expect(mocks.navigate).not.toHaveBeenCalled();
    expect(drawer).toBeInTheDocument();
  });

  it('requires record content and saves a note for the selected node', async () => {
    const user = userEvent.setup();
    render(<RecruitmentQuality />);
    await user.click(await screen.findByRole('button', { name: /一面.*查看依据/ }));
    expect(screen.queryByRole('button', { name: '记录例外' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '更新进展 / 催办' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '登记异常处理结果' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '补充处理记录' }));
    const modal = screen.getAllByRole('dialog').at(-1)!;
    await user.click(within(modal).getByRole('button', { name: '保存记录' }));
    expect(await within(modal).findByText('请填写记录内容')).toBeInTheDocument();
    expect(request.post).not.toHaveBeenCalled();
    fireEvent.change(within(modal).getByRole('textbox'), { target: { value: '面试官出差，主管批准后补' } });
    await user.click(within(modal).getByRole('button', { name: '保存记录' }));
    await waitFor(() => expect(request.post).toHaveBeenCalledWith('/recruitment-quality/bindings/binding/nodes/review%3Apanel/actions', {
      kind: 'note', reason: '面试官出差，主管批准后补',
    }));
  }, 15000);

  it('does not offer configuration or exception controls to an interviewer', async () => {
    mocks.role = 'interviewer';
    const user = userEvent.setup();
    render(<RecruitmentQuality />);
    await user.click(await screen.findByRole('button', { name: /一面.*查看依据/ }));
    expect(screen.queryByRole('button', { name: '流程规则' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '补充处理记录' })).not.toBeInTheDocument();
    expect(request.get).not.toHaveBeenCalledWith('/recruitment-quality/config');
  });

  it('offers explicit activation rather than fabricated zero scores', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => url.endsWith('/config') ? settings : { ...report, enabled: false, people: [], nodes: [] });
    render(<RecruitmentQuality />);
    expect(await screen.findByRole('button', { name: '启用标准流程' })).toBeInTheDocument();
    expect(screen.queryByText('66.7%')).not.toBeInTheDocument();
  });

  it('includes historical evidence by default and shows only the completeness metric', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => url.endsWith('/config') ? settings : {
      ...report, people: [], nodes: [], summary: { ...metrics, process_rate: null,
        completed_nodes: 0, required_nodes: 0,
        overdue_count: 0, missing_count: 0, unknown_count: 0, historical_count: 0, longest_overdue_hours: 0 },
    });
    render(<RecruitmentQuality />);
    expect(await screen.findByText('当前范围暂无人员流程记录')).toBeInTheDocument();
    expect(request.get).toHaveBeenCalledWith('/recruitment-quality/overview', { params: {} });
    expect(screen.queryByText('数据规范率')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '笔试' })).not.toBeInTheDocument();
    expect(screen.queryByText('暂无启用后的新流程记录')).not.toBeInTheDocument();
    expect(screen.queryByText('仅统计启用后的流程。历史记录不计入完整率、规范率、人员数量、超时和提醒，可单独查看。')).not.toBeInTheDocument();
    expect(screen.queryByText('张三')).not.toBeInTheDocument();
  });

  it('publishes independently configurable workday deadlines through the existing settings entry', async () => {
    const user = userEvent.setup();
    render(<RecruitmentQuality />);
    await user.click(await screen.findByRole('button', { name: '流程规则' }));
    const modal = await screen.findByRole('dialog');
    expect(within(modal).getByLabelText('评审意见交齐 → HR决策（工作日）')).toHaveValue('1');
    expect(within(modal).queryByLabelText('等待反馈期间更新进展（工作日）')).not.toBeInTheDocument();
    const offerDays = within(modal).getByLabelText('最终面试通过 / 重开 → 发送Offer（工作日）');
    fireEvent.change(offerDays, { target: { value: '3' } });
    expect(within(modal).queryByText('笔试为必需步骤')).not.toBeInTheDocument();
    await user.click(within(modal).getByRole('button', { name: '发布新版本' }));
    await waitFor(() => expect(request.post).toHaveBeenCalledWith('/recruitment-quality/policies', {
      name: '标准招聘流程', position_id: null, rules: { ...settings.defaults, offer_send_days: 3 },
    }));
  }, 15000);

  it('allows the responsible HR to add a note while the flow is paused', async () => {
    mocks.role = 'hr';
    vi.mocked(request.get).mockImplementation(async (url: string) => url.endsWith('/config') ? settings : {
      ...report, nodes: [{ ...report.nodes[0], executor_id: 'hr', paused: true, status: 'paused' }],
    });
    const user = userEvent.setup();
    render(<RecruitmentQuality />);
    await user.click(await screen.findByRole('button', { name: /一面.*查看依据/ }));
    expect(screen.queryByRole('button', { name: '暂停计时' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '补充处理记录' }));
    const modal = screen.getAllByRole('dialog').at(-1)!;
    fireEvent.change(within(modal).getByRole('textbox'), { target: { value: '已联系面试官，等待反馈' } });
    await user.click(within(modal).getByRole('button', { name: '保存记录' }));
    await waitFor(() => expect(request.post).toHaveBeenCalledWith(
      '/recruitment-quality/bindings/binding/nodes/review%3Apanel/actions',
      { kind: 'note', reason: '已联系面试官，等待反馈' },
    ));
  }, 15000);

  it('applies the selected page size and then pages through process details', async () => {
    const nodes = Array.from({ length: 25 }, (_, i) => ({
      ...report.nodes[0], id: `node-${i + 1}`, resume_id: `resume-${i + 1}`, binding_id: `binding-${i + 1}`, candidate_name: `分页候选人${i + 1}`,
    })).flatMap(n => [n, { ...n, id: n.id + '/screen', key: 'screening', stage: 'screening', label: '初筛', status: 'complete', complete: true, overdue: false }]);
    vi.mocked(request.get).mockImplementation(async (url: string) => url.endsWith('/config') ? settings : { ...report, nodes });
    render(<RecruitmentQuality />);
    expect(await screen.findByText('分页候选人10')).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(10);
    expect(screen.queryByText('分页候选人11')).not.toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Page Size' }));
    fireEvent.click(await screen.findByText(/20\s*\/\s*page/i));
    expect(request.get).toHaveBeenCalledTimes(2);
    expect(await screen.findByText('分页候选人20')).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(20);
    expect(screen.queryByText('分页候选人21')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle('Next Page'));
    expect(await screen.findByText('分页候选人21')).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(5);
    expect(screen.queryByText('分页候选人1')).not.toBeInTheDocument();
  });

  it('keeps personnel page size independent and lets users reduce it again after showing all people', async () => {
    const people = Array.from({ length: 55 }, (_, i) => ({
      ...report.people[0], user_id: `hr-${i + 1}`, name: `分页负责人${i + 1}`,
    }));
    const nodes = Array.from({ length: 25 }, (_, i) => ({
      ...report.nodes[0], id: `node-${i + 1}`, resume_id: `resume-${i + 1}`, binding_id: `binding-${i + 1}`, candidate_name: `分页候选人${i + 1}`,
    }));
    vi.mocked(request.get).mockImplementation(async (url: string) => url.endsWith('/config') ? settings : { ...report, people, nodes });
    render(<RecruitmentQuality />);
    const panel = within((await screen.findByRole('heading', { name: '人员总览' })).closest('.quality-panel') as HTMLElement);
    expect(await panel.findByText('分页负责人10')).toBeInTheDocument();
    fireEvent.mouseDown(panel.getByRole('combobox', { name: 'Page Size' }));
    fireEvent.click(await screen.findByText(/100\s*\/\s*page/i));
    expect(await panel.findByText('分页负责人55')).toBeInTheDocument();
    expect(screen.queryByText('分页候选人11')).not.toBeInTheDocument();
    fireEvent.mouseDown(panel.getByRole('combobox', { name: 'Page Size' }));
    fireEvent.click(await screen.findByText(/10\s*\/\s*page/i, { selector: '.ant-select-item-option-content' }));
    expect(panel.queryByText('分页负责人11')).not.toBeInTheDocument();
  });

  it('renders one card per candidate and opens each stage without repeating the candidate name', async () => {
    const nodes = [report.nodes[0], { ...report.nodes[0], id: 'binding/screening', key: 'screening',
      stage: 'screening', label: '初筛', status: 'complete', complete: true, overdue: false }];
    vi.mocked(request.get).mockImplementation(async (url: string) => url.endsWith('/config') ? settings : { ...report, nodes });
    const user = userEvent.setup();
    render(<RecruitmentQuality />);
    const card = await screen.findByRole('article', { name: '张三的招聘流程' });
    expect(screen.getAllByRole('article')).toHaveLength(1);
    expect(within(card).getAllByText('张三')).toHaveLength(1);
    expect(within(card).getByRole('button', { name: /初筛.*查看依据/ })).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: /一面.*查看依据/ })).toBeInTheDocument();
    await user.click(within(card).getByRole('button', { name: /初筛.*查看依据/ }));
    expect(await within(screen.getByRole('dialog')).findByText('按时完成')).toBeInTheDocument();
  });
});
