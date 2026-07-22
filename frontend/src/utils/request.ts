import axios from 'axios';

const request: any = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  timeout: 10000,
});

const isUnauthenticatedEndpoint = (url?: string) => (
  ['/auth/login', '/auth/tenants', '/auth/token'].includes(url || '')
);

request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token && !isUnauthenticatedEndpoint(config.url)) {
      config.headers.Authorization = `Bearer ${token}`;
    } else if (isUnauthenticatedEndpoint(config.url) && config.headers) {
      delete config.headers.Authorization;
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
    if (sessionIsInvalid) {
      localStorage.removeItem('token');
      if (window.location.pathname !== '/login') window.location.href = '/login';
    }
    return Promise.reject(error);
  },
);

export default request;
