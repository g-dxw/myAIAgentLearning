export interface Schedule {
  id: number;
  worker_id: number;
  patient_id: number;
  start_time: string;
  end_time: string;
  status: 'assigned' | 'in_progress' | 'completed' | 'cancelled';
  worker_name?: string;
  patient_name?: string;
}

export interface ScheduleLog {
  id: number;
  schedule_id: number;
  action: string;
  operator_id: number;
  original_worker_id?: number;
  new_worker_id?: number;
  remark?: string;
  created_at: string;
}

export interface ScheduleSlot {
  hour: number;
  schedule_id: number | null;
  patient_id?: number | null;
  patient_name?: string | null;
  worker_id?: number | null;
  worker_name?: string | null;
  status: string | null;
}

export interface ScheduleRow {
  worker_id?: number;
  worker_name?: string;
  patient_id?: number;
  patient_name?: string;
  slots: ScheduleSlot[];
}

export interface ScheduleViewData {
  view: 'worker' | 'patient';
  date: string;
  rows: ScheduleRow[];
}

export interface ScheduleFormData {
  worker_id: number;
  patient_id: number;
  start_time: string;
  end_time: string;
}

export interface MyScheduleItem {
  id: number;
  worker_id: number;
  patient_id: number;
  patient_name: string | null;
  start_time: string;
  end_time: string;
  status: string;
}
