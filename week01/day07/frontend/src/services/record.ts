import { request } from './request';
import type { ApiResponse, PageResult } from '../types/api';
import type { CareRecord } from '../types/record';

export function listRecords(params?: {
  page?: number;
  pageSize?: number;
  patient_id?: number;
  worker_id?: number;
}): Promise<PageResult<CareRecord>> {
  return request<PageResult<CareRecord>>({
    method: 'GET',
    url: '/api/records',
    params,
  });
}

export function listMyRecords(page = 1, pageSize = 20): Promise<PageResult<CareRecord>> {
  return request<PageResult<CareRecord>>({
    method: 'GET',
    url: '/api/records/my',
    params: { page, pageSize },
  });
}

export function getRecord(id: number): Promise<ApiResponse<CareRecord>> {
  return request<ApiResponse<CareRecord>>({
    method: 'GET',
    url: `/api/records/${id}`,
  });
}
