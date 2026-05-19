export interface CheckinRecord {
  id: number;
  worker_id: number;
  patient_id: number;
  schedule_id: number | null;
  start_time: string;
  end_time: string | null;
  content: string | null;
  status: 'started' | 'completed' | 'absent';
  is_makeup: boolean;
  created_at: string;
  patient_name?: string;
  worker_name?: string;
}

export interface CheckinStartData {
  schedule_id: number;
}

export interface CheckinSubmitData {
  content: string;
}

export interface CheckinMakeupData {
  patient_id: number;
  start_time: string;
  end_time: string;
  content: string;
}
