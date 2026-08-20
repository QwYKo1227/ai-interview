import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import request from '../../utils/request';
import ResumesList from './List';

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'admin-1', role: 'admin' } }),
}));

const resumes = Array.from({ length: 11 }, (_, index) => ({
  id: `resume-${index + 1}`,
  candidate_name: `Candidate ${index + 1}`,
  contact: `candidate-${index + 1}@example.com`,
  position_id: 'position-1',
  position: { title: 'Engineer' },
  status: 'pending_screening',
  match_score: 80,
  parse_status: 'completed',
}));

describe('ResumesList pagination', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('applies the selected number of resumes per page', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => (
      url === '/resumes' ? resumes : []
    ));
    const { container } = render(
      <MemoryRouter>
        <ResumesList />
      </MemoryRouter>,
    );

    expect(await screen.findByText('Candidate 10')).toBeInTheDocument();
    expect(screen.queryByText('Candidate 11')).not.toBeInTheDocument();

    const pageSizeSelector = screen.getByRole('combobox', { name: 'Page Size' });
    expect(container.querySelector('.ant-pagination-options-size-changer')).toBeInTheDocument();
    fireEvent.mouseDown(pageSizeSelector);
    fireEvent.click(await screen.findByText(/20\s*\/\s*page/i));

    await waitFor(() => {
      expect(screen.getByText('Candidate 11')).toBeInTheDocument();
    });
  });

  it('opens other resumes from the clickable duplicate badge', async () => {
    const user = userEvent.setup();
    const duplicateResume = {
      ...resumes[0],
      candidate_name: '王辰',
      contact: '13761339592',
      duplicate_resume_count: 2,
    };
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url === '/resumes') return [duplicateResume];
      if (url === '/resumes/resume-1/duplicates') {
        return [{
          id: 'resume-history',
          candidate_name: '王辰',
          position_id: 'position-history',
          position: { id: 'position-history', title: '历史后端岗位' },
          status: 'pending_interview',
          match_score: 86,
          parse_status: 'success',
          created_at: '2025-08-12T00:00:00Z',
        }];
      }
      return [];
    });

    render(
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<ResumesList />} />
          <Route path="/resumes/:id" element={<div>其他简历详情页</div>} />
        </Routes>
      </MemoryRouter>,
    );

    await user.click(await screen.findByText('2份简历'));
    expect(request.get).toHaveBeenCalledWith('/resumes/resume-1/duplicates');
    await user.click(await screen.findByRole('button', { name: /历史后端岗位/ }));
    expect(await screen.findByText('其他简历详情页')).toBeInTheDocument();
  });

  it('allows a candidate entering the next round to schedule another interview', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => (
      url === '/resumes'
        ? [{ ...resumes[0], status: 'pending_next_interview' }]
        : []
    ));

    render(
      <MemoryRouter>
        <ResumesList />
      </MemoryRouter>,
    );

    await screen.findByText('Candidate 1');
    expect(screen.getByRole('button', { name: '安排面试' })).toBeInTheDocument();
  });
});
