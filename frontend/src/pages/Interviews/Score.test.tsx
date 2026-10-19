import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import InterviewScore from './Score';
import request from '../../utils/request';

vi.mock('../../utils/request', () => ({ default: { get: vi.fn(), put: vi.fn() } }));
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'me', role: 'interviewer' } }),
}));

const interview = {
  id: 'interview-1',
  status: 'in_progress',
  lifecycle_state: 'in_progress',
  panel_members: ['me'],
  questions: [
    { title: '系统设计', content: '如何设计任务调度系统？', resume_association: '核实调度项目的个人贡献', follow_up: ['如何处理重复任务？'] },
    { title: '项目复盘', content: '项目中最困难的决策是什么？', follow_up: '如何衡量改进效果？' },
  ],
  resume: {
    candidate_name: '测试候选人',
    match_score: 0,
    ai_review: '### ✅ 优势\n有调度系统经验\n\n### ⚠️ 不足\n缺少规模数据\n\n### 💡 综合建议\n优先核实高并发实践',
    hr_review: '关注跨团队沟通方式',
  },
};

function renderScore() {
  return render(
    <MemoryRouter initialEntries={['/interviews/interview-1/score']}>
      <Routes><Route path="/interviews/:id/score" element={<InterviewScore />} /></Routes>
    </MemoryRouter>,
  );
}

describe('InterviewScore workspace', () => {
  beforeEach(() => {
    vi.mocked(request.get).mockReset().mockImplementation(async (url) => (
      String(url).endsWith('/notes') ? [{ interviewer_id: 'me', notes: '已有观察' }] : interview
    ));
    vi.mocked(request.put).mockReset().mockResolvedValue({});
  });
  afterEach(cleanup);

  it('shows resume assessment and current follow-ups in the interview assistant', async () => {
    renderScore();
    const assistant = await screen.findByRole('complementary', { name: '面试辅助' });
    expect(within(assistant).getByText('候选人简历评估')).toBeInTheDocument();
    expect(within(assistant).getByText('岗位匹配 0 分')).toBeInTheDocument();
    expect(within(assistant).getByText('有调度系统经验')).toBeInTheDocument();
    expect(within(assistant).getByText('关注跨团队沟通方式')).toBeInTheDocument();
    expect(within(assistant).getByText('如何处理重复任务？')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /下一题/ }));
    expect(within(assistant).getByText('如何衡量改进效果？')).toBeInTheDocument();
    expect(within(assistant).queryByText('如何处理重复任务？')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('textbox', { name: '实时面试笔记' })).toHaveValue('已有观察'));
  });

  it('keeps notes compact, expands without losing edits and saves on blur', async () => {
    renderScore();
    const notes = await screen.findByRole('textbox', { name: '实时面试笔记' });
    await waitFor(() => expect(notes).toHaveValue('已有观察'));
    expect(notes).toHaveAttribute('rows', '2');
    fireEvent.change(notes, { target: { value: '需进一步核实项目贡献' } });
    fireEvent.click(screen.getByRole('button', { name: '展开笔记' }));
    expect(notes).toHaveAttribute('rows', '7');
    expect(notes).toHaveValue('需进一步核实项目贡献');
    fireEvent.click(screen.getByRole('button', { name: '收起笔记' }));
    expect(notes).toHaveAttribute('rows', '2');
    fireEvent.blur(notes);
    await waitFor(() => expect(request.put).toHaveBeenCalledWith('/interviews/interview-1/notes', { notes: '需进一步核实项目贡献' }));
  });

  it('keeps the assessment and suggestions available without generated questions', async () => {
    vi.mocked(request.get).mockImplementation(async (url) => (
      String(url).endsWith('/notes') ? [] : { ...interview, questions: [] }
    ));
    renderScore();
    expect(await screen.findByText('面试分析建议')).toBeInTheDocument();
    const focus = screen.getByText('简历初审建议').closest<HTMLElement>('.interview-focus-section')!;
    expect(within(focus).getByText('优先核实高并发实践')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '实时面试笔记' })).toHaveAttribute('rows', '2');
    expect(screen.queryByText('面试题目')).not.toBeInTheDocument();
  });

  it('provides a useful fallback when resume evaluation is missing', async () => {
    vi.mocked(request.get).mockImplementation(async (url) => (
      String(url).endsWith('/notes') ? [] : { ...interview, resume: null, questions: [] }
    ));
    renderScore();
    expect(await screen.findByText('暂无简历评估，可结合左侧简历核实岗位相关经历。')).toBeInTheDocument();
    expect(screen.getByText('围绕岗位要求与简历中的待核实经历提问，重点确认本人贡献、关键决策和实际结果。')).toBeInTheDocument();
  });
});
