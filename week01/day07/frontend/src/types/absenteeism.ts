export interface AbsenteeismRecord {
  id: number;
  schedule_id: number;
  worker_id: number;
  patient_id: number;
  status: 'absent' | 'corrected';
  auto_marked_at: string;
  corrected_at: string | null;
  corrected_by: number | null;
  correction_reason: string | null;
  score: number | null;
  created_at: string;
  worker_name?: string;
  patient_name?: string;
}
