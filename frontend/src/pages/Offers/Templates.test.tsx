import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import request from '../../utils/request';
import OfferTemplates from './Templates';

vi.mock('../../utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it('allows an Offer template to select a position beyond the first 100', async () => {
  const positions = Array.from({ length: 105 }, (_, index) => ({
    id: `position-${index + 1}`, title: `岗位${index + 1}`,
  }));
  vi.mocked(request.get).mockImplementation(async (url: string) => {
    if (url === '/positions') return positions;
    if (url.startsWith('/positions?')) return positions.slice(0, 100);
    return { items: [] };
  });

  render(<OfferTemplates />);
  await waitFor(() => expect(request.get).toHaveBeenCalledWith('/positions'));
  fireEvent.click(screen.getByRole('button', { name: /新建模板/ }));
  const selector = screen.getByRole('combobox', { name: '关联岗位（可选）' });
  fireEvent.mouseDown(selector);
  fireEvent.keyDown(selector, { key: 'ArrowUp', keyCode: 38 });
  expect(await screen.findByRole('option', { name: '岗位105' })).toBeInTheDocument();
});
