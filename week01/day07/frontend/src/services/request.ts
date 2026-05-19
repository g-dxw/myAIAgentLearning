import { getToken, clearAuth } from '../utils/storage';

const BASE_URL = ''; // 开发时由 Vite proxy 转发到 localhost:8000

interface RequestConfig {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  url: string;
  params?: Record<string, string | number | undefined>;
  body?: unknown;
}

export async function request<T>(config: RequestConfig): Promise<T> {
  const { method, url, params, body } = config;

  let fullUrl = `${BASE_URL}${url}`;
  if (params) {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== '') {
        searchParams.append(key, String(value));
      }
    });
    const qs = searchParams.toString();
    if (qs) fullUrl += `?${qs}`;
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(fullUrl, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (response.status === 401) {
    clearAuth();
    window.location.href = '/login';
    throw new Error('登录已过期，请重新登录');
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ message: '请求失败' }));
    throw new Error(errorData.message || `HTTP ${response.status}`);
  }

  return response.json();
}
