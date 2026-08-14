export type TenantStatus = 'active' | 'inactive';

export interface PlatformTenantAdmin {
  id: string;
  email: string;
  full_name?: string | null;
  is_active: boolean;
}

export interface PlatformTenant {
  id: string;
  code: string;
  name: string;
  logo_url?: string | null;
  status: TenantStatus;
  created_at: string;
  updated_at: string;
}

export interface PlatformTenantDetail extends PlatformTenant {
  admins: PlatformTenantAdmin[];
}

export interface PlatformLoginPayload { email: string; password: string }

export interface TenantOnboardingPayload {
  code: string;
  name: string;
  admin_email: string;
  admin_password: string;
}
