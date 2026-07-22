import { describe, expect, it } from 'vitest';
import { resolveTenantSelection } from './tenantRouting';
import type { TenantSummary } from '../types/tenant';

const tenants: TenantSummary[] = [
  {
    id: '1',
    code: 'careray',
    name: '凯锐招聘',
    primary_domain: 'interview.careray.com',
  },
];

describe('resolveTenantSelection', () => {
  it('selects the company for a matching dedicated domain', () => {
    expect(resolveTenantSelection('INTERVIEW.CARERAY.COM.:443', tenants)?.code).toBe('careray');
  });

  it('does not lock a company for an unknown domain', () => {
    expect(resolveTenantSelection('interview.unknown.com', tenants)).toBeUndefined();
  });

  it('does not lock a company while using localhost in development', () => {
    expect(resolveTenantSelection('localhost:5173', tenants)).toBeUndefined();
  });
});
