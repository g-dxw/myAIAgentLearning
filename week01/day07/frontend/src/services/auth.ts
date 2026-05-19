import { request } from './request';
import type { LoginForm, LoginResult, User } from '../types/auth';
import type { ApiResponse } from '../types/api';

export function login(data: LoginForm): Promise<ApiResponse<LoginResult>> {
  return request<ApiResponse<LoginResult>>({
    method: 'POST',
    url: '/api/auth/login',
    body: data,
  });
}

export function getMe(): Promise<ApiResponse<User>> {
  return request<ApiResponse<User>>({
    method: 'GET',
    url: '/api/auth/me',
  });
}
