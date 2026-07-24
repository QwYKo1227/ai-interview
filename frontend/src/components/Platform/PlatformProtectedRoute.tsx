import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { usePlatformAuth } from '../../contexts/PlatformAuthContext';

const PlatformProtectedRoute = ({ children }: { children: ReactNode }) => {
  const { isAuthenticated } = usePlatformAuth();

  if (!isAuthenticated) return <Navigate replace to="/platform/login" />;

  return <>{children}</>;
};

export default PlatformProtectedRoute;
