import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import request from '../../utils/request';
import InterviewsList from './List';

vi.mock('../../utils/request', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'hr', role: 'hr' } }) }));
vi.mock('./InterviewCalendar', () => ({ default: () => null }));
vi.mock('../../components/ScheduleInterviewModal', () => ({
  default: ({ resume }: { resume: { id: string } }) => <div role="dialog" aria-label="安排面试">{resume.id}</div>,
}));

const interview = {
  id: 'i1', resume_id: 'r1', position_id: 'p1', round: 1, lifecycle_state: 'scheduled', status: 'scheduled',
  resume: { candidate_name: '张三' }, position: { title: '工程师' }, panel_members: [],
  interview_time: '2026-11-05T01:00:00Z', interview_end_time: '2026-11-05T02:00:00Z',
  interview_type: 'onsite', interview_location: '一号会议室',
};

describe('interview business links', () => {
  beforeEach(() => {
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes/r1') return { id: 'r1', position_id: 'p1', status: 'pending_next_interview' };
      if (url === '/interviews/i1') return interview;
      if (url === '/interviews') return [interview, { ...interview, id: 'i2', round: 2 }];
      return [];
    });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('opens scheduling with the selected candidate already supplied', async () => {
    window.history.replaceState(null, '', '/interviews?candidate=r1&position=p1&action=schedule');
    render(<MemoryRouter><InterviewsList /></MemoryRouter>);
    expect(await screen.findByRole('dialog', { name: '安排面试' })).toHaveTextContent('r1');
    expect(request.post).not.toHaveBeenCalled();
  });

  it('opens the exact interview schedule and excludes other rounds from the list', async () => {
    window.history.replaceState(null, '', '/interviews?candidate=r1&position=p1&interview_id=i1&action=edit');
    render(<MemoryRouter><InterviewsList /></MemoryRouter>);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('编辑面试安排')).toBeInTheDocument();
    expect(within(dialog).getByRole('textbox', { name: '面试地点' })).toHaveValue('一号会议室');
    expect(screen.getByText('第1轮')).toBeInTheDocument();
    expect(screen.queryByText('第2轮')).not.toBeInTheDocument();
    expect(request.post).not.toHaveBeenCalled();
  });

  it('does not open scheduling after the candidate has changed positions', async () => {
    window.history.replaceState(null, '', '/interviews?candidate=r1&position=old-position&action=schedule');
    render(<MemoryRouter><InterviewsList /></MemoryRouter>);
    await waitFor(() => expect(request.get).toHaveBeenCalledWith('/resumes/r1'));
    expect(screen.queryByRole('dialog', { name: '安排面试' })).not.toBeInTheDocument();
    expect(request.post).not.toHaveBeenCalled();
  });
});
