import { request } from './request';
import type { Worker, WorkerFormData } from '../types/worker';
import type { ApiResponse, PageResult } from '../types/api';

export function getWorkers(params?: {
  page?: number;
  pageSize?: number;
  name?: string;
  status?: string;
}): Promise<PageResult<Worker>> {
  return request<PageResult<Worker>>({
    method: 'GET',
    url: '/api/workers',
    params,
  });
}

export function getWorker(id: number): Promise<ApiResponse<Worker>> {
  return request<ApiResponse<Worker>>({
    method: 'GET',
    url: `/api/workers/${id}`,
  });
}

export function createWorker(data: WorkerFormData): Promise<ApiResponse<Worker>> {
  return request<ApiResponse<Worker>>({
    method: 'POST',
    url: '/api/workers',
    body: data,
  });
}

export function updateWorker(id: number, data: WorkerFormData): Promise<ApiResponse<Worker>> {
  return request<ApiResponse<Worker>>({
    method: 'PUT',
    url: `/api/workers/${id}`,
    body: data,
  });
}

export function updateWorkerStatus(id: number, status: string): Promise<ApiResponse<Worker>> {
  return request<ApiResponse<Worker>>({
    method: 'PATCH',
    url: `/api/workers/${id}/status`,
    body: { status },
  });
}

export function deleteWorker(id: number): Promise<ApiResponse<unknown>> {
  return request<ApiResponse<unknown>>({
    method: 'DELETE',
    url: `/api/workers/${id}`,
  });
}

export function resetPassword(id: number): Promise<ApiResponse<{ password: string }>> {
  return request<ApiResponse<{ password: string }>>({
    method: 'PATCH',
    url: `/api/workers/${id}/reset-password`,
  });
}
