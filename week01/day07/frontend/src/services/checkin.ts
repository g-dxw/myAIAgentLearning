import { request } from './request';
import type { ApiResponse } from '../types/api';
import type { CheckinRecord, CheckinStartData, CheckinSubmitData, CheckinMakeupData } from '../types/checkin';

export function startCheckin(data: CheckinStartData): Promise<ApiResponse<CheckinRecord>> {
  return request<ApiResponse<CheckinRecord>>({
    method: 'POST',
    url: '/api/checkin',
    body: data,
  });
}

export function submitCheckin(checkinId: number, data: CheckinSubmitData): Promise<ApiResponse<CheckinRecord>> {
  return request<ApiResponse<CheckinRecord>>({
    method: 'POST',
    url: `/api/checkin/${checkinId}/submit`,
    body: data,
  });
}

export function makeupCheckin(data: CheckinMakeupData): Promise<ApiResponse<CheckinRecord>> {
  return request<ApiResponse<CheckinRecord>>({
    method: 'POST',
    url: '/api/checkin/makeup',
    body: data,
  });
}

export function getMyCheckins(): Promise<ApiResponse<CheckinRecord[]>> {
  return request<ApiResponse<CheckinRecord[]>>({
    method: 'GET',
    url: '/api/checkin/my',
  });
}
