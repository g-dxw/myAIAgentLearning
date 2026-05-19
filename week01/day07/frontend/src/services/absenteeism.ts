import { request } from './request';
import type { ApiResponse, PageResult } from '../types/api';
import type { AbsenteeismRecord } from '../types/absenteeism';

export function listAbsenteeism(params?: {
  page?: number;
  pageSize?: number;
  worker_id?: number;
  start_date?: string;
  end_date?: string;
}): Promise<PageResult<AbsenteeismRecord>> {
  return request<PageResult<AbsenteeismRecord>>({
    method: 'GET',
    url: '/api/absenteeism',
    params,
  });
}

export function correctAbsenteeism(id: number, reason: string): Promise<ApiResponse<unknown>> {
  return request<ApiResponse<unknown>>({
    method: 'PATCH',
    url: `/api/absenteeism/${id}/correct`,
    body: { correction_reason: reason },
  });
}
