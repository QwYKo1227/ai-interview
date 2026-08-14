import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';

import { useAuth } from '../contexts/AuthContext';

type RoleProtectedRouteProps = {
  children: ReactNode;
  roles: Array<'admin' | 'hr' | 'interviewer'>;
  redirectTo?: string;
};

const RoleProtectedRoute = ({ children, roles, redirectTo = '/dashboard' }: RoleProtectedRouteProps) => {
  const { user } = useAuth();
  const role = (user as any)?.role?.value ?? user?.role;

  if (!role || !roles.includes(role)) {
    return <Navigate to={redirectTo} replace />;
  }

  return <>{children}</>;
};

export default RoleProtectedRoute;
