export interface CareRecord {
  id: number;
  patient_id: number;
  worker_id: number;
  content: string;
  created_at: string;
  patient_name?: string;
  worker_name?: string;
}
