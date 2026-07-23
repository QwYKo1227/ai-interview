import { createContext, useContext, useState } from 'react';
import type { ReactNode } from 'react';

interface PlatformAuthContextValue {
  isAuthenticated: boolean;
  login: (token: string) => void;
  logout: () => void;
}

const PlatformAuthContext = createContext<PlatformAuthContextValue | undefined>(undefined);

export const PlatformAuthProvider = ({ children }: { children: ReactNode }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(() => (
    Boolean(localStorage.getItem('platform_token'))
  ));

  const login = (token: string) => {
    localStorage.setItem('platform_token', token);
    setIsAuthenticated(true);
  };

  const logout = () => {
    localStorage.removeItem('platform_token');
    setIsAuthenticated(false);
  };

  return (
    <PlatformAuthContext.Provider value={{ isAuthenticated, login, logout }}>
      {children}
    </PlatformAuthContext.Provider>
  );
};

export const usePlatformAuth = () => {
  const context = useContext(PlatformAuthContext);
  if (context === undefined) throw new Error('usePlatformAuth must be used within a PlatformAuthProvider');
  return context;
};
