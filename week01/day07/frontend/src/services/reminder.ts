import { request } from './request';
import type { PageResult } from '../types/api';
import type { Reminder } from '../types/reminder';

export function listReminders(page = 1, pageSize = 20): Promise<PageResult<Reminder>> {
  return request<PageResult<Reminder>>({
    method: 'GET',
    url: '/api/reminders',
    params: { page, pageSize },
  });
}

export function markRead(id: number): Promise<unknown> {
  return request<unknown>({
    method: 'PATCH',
    url: `/api/reminders/${id}/read`,
  });
}
