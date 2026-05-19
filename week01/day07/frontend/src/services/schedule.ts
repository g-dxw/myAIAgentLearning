import { request } from './request';
import type { ApiResponse, PageResult } from '../types/api';
import type { Schedule, ScheduleFormData, ScheduleViewData, ScheduleLog, MyScheduleItem } from '../types/schedule';

export function getScheduleView(date: string, view: 'worker' | 'patient'): Promise<ApiResponse<ScheduleViewData>> {
  return request<ApiResponse<ScheduleViewData>>({
    method: 'GET',
    url: '/api/schedules',
    params: { date, view },
  });
}

export function createSchedule(data: ScheduleFormData): Promise<ApiResponse<Schedule>> {
  return request<ApiResponse<Schedule>>({
    method: 'POST',
    url: '/api/schedules',
    body: data,
  });
}

export function cancelSchedule(id: number): Promise<ApiResponse<unknown>> {
  return request<ApiResponse<unknown>>({
    method: 'DELETE',
    url: `/api/schedules/${id}`,
  });
}

export function getScheduleLogs(page = 1, pageSize = 20): Promise<PageResult<ScheduleLog>> {
  return request<PageResult<ScheduleLog>>({
    method: 'GET',
    url: '/api/schedules/logs',
    params: { page, pageSize },
  });
}

export function getMySchedules(date?: string): Promise<ApiResponse<MyScheduleItem[]>> {
  return request<ApiResponse<MyScheduleItem[]>>({
    method: 'GET',
    url: '/api/schedules/my',
    params: { date },
  });
}
