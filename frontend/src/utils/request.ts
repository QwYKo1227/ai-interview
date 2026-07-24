import axios from 'axios';

const request: any = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  timeout: 10000,
});

const isUnauthenticatedEndpoint = (url?: string) => (
  ['/auth/login', '/auth/tenants', '/auth/token'].includes(url || '')
);

const removeAuthorization = (headers: any) => {
  if (!headers) return;
  if (typeof headers.delete === 'function') {
    headers.delete('Authorization');
    return;
  }
  Object.keys(headers).forEach((key) => {
    if (key.toLowerCase() === 'authorization') delete headers[key];
  });
};

export const getBearerToken = (headers: unknown): string | null => {
  if (!headers || typeof headers !== 'object') return null;

  try {
    const candidate = headers as Record<string, unknown> & { get?: (name: string) => unknown };
    let authorization = typeof candidate.get === 'function'
      ? candidate.get('Authorization')
      : undefined;

    if (typeof authorization !== 'string') {
      const entry = Object.entries(candidate).find(([key]) => key.toLowerCase() === 'authorization');
      authorization = entry?.[1];
    }

    if (typeof authorization !== 'string') return null;
    const match = /^Bearer\s+([^\s]+)$/i.exec(authorization.trim());
    return match?.[1] ?? null;
  } catch {
    return null;
  }
};

request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token && !isUnauthenticatedEndpoint(config.url)) {
      config.headers.Authorization = `Bearer ${token}`;
    } else if (isUnauthenticatedEndpoint(config.url)) {
      removeAuthorization(config.headers);
    }
    return config;
  },
  (error) => Promise.reject(error),
);

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status;
    const detail = error.response?.data?.detail || '';
    const sessionIsInvalid = status === 401 || (status === 403 && detail.includes('禁用'));
    const failedRequestToken = getBearerToken(error.config?.headers);
    const currentToken = localStorage.getItem('token');

    if (sessionIsInvalid && failedRequestToken && failedRequestToken === currentToken) {
      localStorage.removeItem('token');
      if (window.location.pathname !== '/login') window.location.href = '/login';
    }
    return Promise.reject(error);
  },
);

export default request;
