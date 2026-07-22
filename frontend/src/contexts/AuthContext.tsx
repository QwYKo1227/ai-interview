import React, { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { message } from 'antd';
import request from '../utils/request';
import type { TenantSummary } from '../types/tenant';

interface User {
  id: string;
  email: string;
  full_name: string;
  role: 'admin' | 'hr' | 'interviewer';
  tenant?: TenantSummary;
}

interface AuthContextType {
  user: User | null;
  tenant: TenantSummary | null;
  companyName: string | null;
  loading: boolean;
  login: (token: string) => Promise<boolean>;
  logout: () => void;
  refreshUser: () => Promise<boolean>;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [tenant, setTenant] = useState<TenantSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchUser = async (): Promise<boolean> => {
    setTenant(null);
    try {
      const response = await request.get('/auth/me') as User;
      setUser(response);
      setTenant(response.tenant ?? null);
      return true;
    } catch {
      localStorage.removeItem('token');
      setUser(null);
      setTenant(null);
      return false;
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (localStorage.getItem('token')) {
      void fetchUser();
    } else {
      setLoading(false);
    }
  }, []);

  const login = async (token: string) => {
    localStorage.setItem('token', token);
    return fetchUser();
  };

  const logout = () => {
    localStorage.removeItem('token');
    setUser(null);
    setTenant(null);
    message.success('已退出登录');
  };

  return (
    <AuthContext.Provider value={{
      user,
      tenant,
      companyName: tenant?.name ?? null,
      loading,
      login,
      logout,
      refreshUser: fetchUser,
      isAuthenticated: !!user,
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};
