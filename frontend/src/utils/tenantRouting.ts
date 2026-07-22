import type { TenantSummary } from '../types/tenant';

const normalizeHostname = (value: string) => {
  const trimmed = value.trim().toLowerCase();
  if (!trimmed) return '';

  try {
    return new URL(trimmed.includes('://') ? trimmed : `//${trimmed}`, 'https://localhost').hostname
      .replace(/\.+$/, '');
  } catch {
    return trimmed.replace(/^\/+/, '').replace(/:\d+$/, '').replace(/\.+$/, '');
  }
};

export const resolveTenantSelection = (
  hostname: string,
  tenants: TenantSummary[],
): TenantSummary | undefined => {
  const normalizedHostname = normalizeHostname(hostname);
  if (!normalizedHostname || normalizedHostname === 'localhost' || normalizedHostname === '127.0.0.1' || normalizedHostname === '[::1]') {
    return undefined;
  }

  return tenants.find((tenant) => (
    tenant.primary_domain
    && normalizeHostname(tenant.primary_domain) === normalizedHostname
  ));
};
