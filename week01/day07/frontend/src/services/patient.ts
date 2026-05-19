import { request } from './request';
import type { Patient, PatientFormData, SpecialCondition, PatientVersion } from '../types/patient';
import type { ApiResponse, PageResult } from '../types/api';

export function getPatients(params?: {
  page?: number; pageSize?: number; name?: string; status?: string;
}): Promise<PageResult<Patient>> {
  return request<PageResult<Patient>>({ method: 'GET', url: '/api/patients', params });
}

export function getPatient(id: number): Promise<ApiResponse<Patient>> {
  return request<ApiResponse<Patient>>({ method: 'GET', url: `/api/patients/${id}` });
}

export function createPatient(data: PatientFormData): Promise<ApiResponse<Patient>> {
  return request<ApiResponse<Patient>>({ method: 'POST', url: '/api/patients', body: data });
}

export function updatePatient(id: number, data: PatientFormData): Promise<ApiResponse<Patient>> {
  return request<ApiResponse<Patient>>({ method: 'PUT', url: `/api/patients/${id}`, body: data });
}

export function assignWorker(patientId: number, workerId: number): Promise<ApiResponse<Patient>> {
  return request<ApiResponse<Patient>>({
    method: 'POST', url: `/api/patients/${patientId}/assign`, body: { worker_id: workerId },
  });
}

export function getApprovals(params?: {
  page?: number; pageSize?: number;
}): Promise<PageResult<Patient>> {
  return request<PageResult<Patient>>({ method: 'GET', url: '/api/approvals', params });
}

export function approvePatient(id: number): Promise<ApiResponse<Patient>> {
  return request<ApiResponse<Patient>>({ method: 'POST', url: `/api/approvals/${id}/approve` });
}

export function rejectPatient(id: number, reason: string): Promise<ApiResponse<unknown>> {
  return request<ApiResponse<unknown>>({
    method: 'POST', url: `/api/approvals/${id}/reject`, body: { reason },
  });
}

export function getSpecialConditions(patientId: number): Promise<ApiResponse<SpecialCondition[]>> {
  return request<ApiResponse<SpecialCondition[]>>({
    method: 'GET', url: `/api/patients/${patientId}/special-conditions`,
  });
}

export function addSpecialCondition(
  patientId: number, data: { type: string; description: string }
): Promise<ApiResponse<SpecialCondition>> {
  return request<ApiResponse<SpecialCondition>>({
    method: 'POST', url: `/api/patients/${patientId}/special-conditions`, body: data,
  });
}

export function getVersions(patientId: number): Promise<ApiResponse<PatientVersion[]>> {
  return request<ApiResponse<PatientVersion[]>>({
    method: 'GET', url: `/api/patients/${patientId}/versions`,
  });
}
