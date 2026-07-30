import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
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
  const mountedRef = useRef(false);
  const generationRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);

  const invalidatePendingRequest = useCallback(() => {
    generationRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
    return generationRef.current;
  }, []);

  const fetchUser = useCallback(async (): Promise<boolean> => {
    const tokenSnapshot = localStorage.getItem('token');
    const generation = invalidatePendingRequest();
    const controller = new AbortController();
    controllerRef.current = controller;
    const isCurrentGeneration = () => (
      mountedRef.current
      && generationRef.current === generation
    );
    const isCurrentRequest = () => (
      isCurrentGeneration()
      && localStorage.getItem('token') === tokenSnapshot
    );

    if (!tokenSnapshot) {
      if (isCurrentRequest()) setLoading(false);
      return false;
    }

    if (isCurrentRequest()) {
      setLoading(true);
      setTenant(null);
    }

    try {
      const response = await request.get('/auth/me', { signal: controller.signal }) as User;
      if (!isCurrentRequest()) return false;
      setUser(response);
      setTenant(response.tenant ?? null);
      return true;
    } catch {
      if (!isCurrentGeneration() || controller.signal.aborted) return false;
      localStorage.removeItem('token');
      setUser(null);
      setTenant(null);
      return false;
    } finally {
      if (isCurrentGeneration()) {
        setLoading(false);
        if (controllerRef.current === controller) controllerRef.current = null;
      }
    }
  }, [invalidatePendingRequest]);

  useEffect(() => {
    mountedRef.current = true;
    if (localStorage.getItem('token')) {
      void fetchUser();
    } else {
      setLoading(false);
    }

    return () => {
      mountedRef.current = false;
      invalidatePendingRequest();
    };
  }, [fetchUser, invalidatePendingRequest]);

  const login = async (token: string) => {
    invalidatePendingRequest();
    localStorage.setItem('token', token);
    return fetchUser();
  };

  const logout = () => {
    invalidatePendingRequest();
    localStorage.removeItem('token');
    setUser(null);
    setTenant(null);
    setLoading(false);
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

export const useOptionalAuth = () => useContext(AuthContext);
