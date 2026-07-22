export interface TenantSummary {
  id: string;
  code: string;
  name: string;
  logo_url?: string | null;
  primary_domain?: string | null;
}

export interface LoginPayload {
  tenant_code: string;
  email: string;
  password: string;
}
