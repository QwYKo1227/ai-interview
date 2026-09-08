import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import request from '../../utils/request';
import OffersList from './List';

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'admin-1', role: 'admin' } }),
}));

const acceptedOffer = {
  id: 'offer-1',
  resume_id: 'resume-1',
  position_id: 'position-1',
  candidate_name: '张三',
  candidate_email: 'zhangsan@example.com',
  salary_monthly: 30000,
  salary_annual: null,
  salary_structure: null,
  position_title: '研发工程师',
  department: '研发部',
  report_to: null,
  work_location: null,
  work_hours: null,
  onboard_date: null,
  probation_months: 3,
  benefits: null,
  bonus: null,
  special_terms: null,
  notes: null,
  valid_until: null,
  status: 'accepted',
  sent_at: '2026-08-20T00:00:00Z',
  accepted_at: '2026-08-21T00:00:00Z',
  actual_onboarded_at: null,
  departed_at: null,
  departure_recorded_by: null,
  departure_reason: null,
  departure_released_hc: null,
  rejected_at: null,
  rejected_reason: null,
  created_at: '2026-08-19T00:00:00Z',
  updated_at: null,
  hiring_manager_id: 'admin-1',
  hiring_manager_name: '管理员',
  can_decide: true,
  position_info: null,
  resume_info: null,
};

describe('OffersList editing', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('shows an edit action for an accepted Offer', async () => {
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url.startsWith('/offers?')) {
        return { items: [acceptedOffer], total: 1, page: 1, page_size: 10, total_pages: 1 };
      }
      if (url === '/offers/stats') {
        return {
          total_offers: 1,
          pending_offers: 0,
          sent_offers: 0,
          accepted_offers: 1,
          rejected_offers: 0,
          expired_offers: 0,
          acceptance_rate: 100,
          avg_response_days: 1,
        };
      }
      if (url.startsWith('/positions')) return { items: [] };
      if (url.startsWith('/resumes')) return [];
      return { items: [] };
    });

    render(<OffersList />);

    expect(await screen.findByRole('button', { name: '编辑 张三 的 Offer' })).toBeInTheDocument();
  });

  it('shows a departed Offer as departed instead of onboarded', async () => {
    const departedOffer = {
      ...acceptedOffer,
      status: 'departed',
      actual_onboarded_at: '2026-08-25T00:00:00Z',
      departed_at: '2026-09-01T00:00:00Z',
      departure_recorded_by: 'admin-1',
      departure_reason: '员工主动离职',
      departure_released_hc: true,
    };
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url.startsWith('/offers?')) return { items: [departedOffer], total: 1, page: 1, page_size: 10, total_pages: 1 };
      if (url === '/offers/stats') return { total_offers: 1, pending_offers: 0, sent_offers: 0, accepted_offers: 1, rejected_offers: 0, expired_offers: 0, acceptance_rate: 100, avg_response_days: 1 };
      if (url.startsWith('/positions')) return { items: [] };
      if (url.startsWith('/resumes')) return [];
      return { items: [] };
    });

    render(<OffersList />);

    expect(await screen.findByText('已离职')).toBeInTheDocument();
    expect(screen.queryByText('已入职')).not.toBeInTheDocument();
  });

  it('shows the current rejected status for legacy inconsistent onboarding data', async () => {
    const rejectedOffer = {
      ...acceptedOffer,
      status: 'rejected',
      actual_onboarded_at: '2026-08-25T00:00:00Z',
      rejected_at: '2026-09-01T00:00:00Z',
      rejected_reason: 'personal',
    };
    vi.mocked(request.get).mockImplementation(async (url: string) => {
      if (url.startsWith('/offers?')) {
        return { items: [rejectedOffer], total: 1, page: 1, page_size: 10, total_pages: 1 };
      }
      if (url === '/offers/stats') {
        return {
          total_offers: 1, pending_offers: 0, sent_offers: 0,
          accepted_offers: 0, rejected_offers: 1, expired_offers: 0,
          acceptance_rate: 0, avg_response_days: null,
        };
      }
      if (url.startsWith('/positions')) return { items: [] };
      if (url.startsWith('/resumes')) return [];
      return { items: [] };
    });

    render(<OffersList />);

    expect(await screen.findByText('已拒绝')).toBeInTheDocument();
    expect(screen.queryByText('已入职')).not.toBeInTheDocument();
  });
});
