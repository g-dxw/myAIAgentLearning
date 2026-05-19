export interface Reminder {
  id: number;
  worker_id: number;
  schedule_id: number;
  type: string;
  message: string;
  is_read: boolean;
  created_at: string;
}
