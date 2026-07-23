import axios from 'axios';
import { getBearerToken } from './request';

const platformRequest = axios.create({
  baseURL: '/api',
  timeout: 10000,
});

const platformLoginUrl = '/platform/auth/login';

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

platformRequest.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('platform_token');
    if (config.url === platformLoginUrl) {
      removeAuthorization(config.headers);
    } else if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error),
);

platformRequest.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const failedRequestToken = getBearerToken(error.config?.headers);
    const currentToken = localStorage.getItem('platform_token');

    if (error.response?.status === 401 && failedRequestToken && failedRequestToken === currentToken) {
      localStorage.removeItem('platform_token');
      if (window.location.pathname !== '/platform/login') window.location.href = '/platform/login';
    }
    return Promise.reject(error);
  },
);

export default platformRequest;
