import { request } from './request';
import type { ApiResponse } from '../types/api';
import type { Session, WorkerPatient, SessionResponse, AddMessageResponse, ExtractResult } from '../types/session';

export function getWorkerPatients(): Promise<ApiResponse<WorkerPatient[]>> {
  return request<ApiResponse<WorkerPatient[]>>({
    method: 'GET',
    url: '/api/worker/patients',
  });
}

export function createSession(patient_id: number): Promise<ApiResponse<Session>> {
  return request<ApiResponse<Session>>({
    method: 'POST',
    url: '/api/sessions',
    body: { patient_id },
  });
}

export function getSession(sessionId: number): Promise<ApiResponse<SessionResponse>> {
  return request<ApiResponse<SessionResponse>>({
    method: 'GET',
    url: `/api/sessions/${sessionId}`,
  });
}

export function addMessage(sessionId: number, content: string): Promise<ApiResponse<AddMessageResponse>> {
  return request<ApiResponse<AddMessageResponse>>({
    method: 'POST',
    url: `/api/sessions/${sessionId}/messages`,
    body: { content },
  });
}

export function extractInfo(sessionId: number): Promise<ApiResponse<ExtractResult>> {
  return request<ApiResponse<ExtractResult>>({
    method: 'POST',
    url: `/api/sessions/${sessionId}/extract`,
  });
}

export function confirmSubmit(sessionId: number, data: ExtractResult): Promise<ApiResponse<unknown>> {
  return request<ApiResponse<unknown>>({
    method: 'POST',
    url: `/api/sessions/${sessionId}/confirm`,
    body: data,
  });
}
