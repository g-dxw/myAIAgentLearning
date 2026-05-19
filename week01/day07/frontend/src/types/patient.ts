export interface Patient {
  id: number;
  name: string;
  age: number;
  gender: string;
  insurance_type: string;
  phone: string;
  address: string;
  emergency_contact: string;
  guardian_info: string | null;
  disease_info: string | null;
  care_requirements: string | null;
  personality: string | null;
  status: 'active' | 'pending';
  assigned_worker_id: number | null;
  assigned_worker_name: string | null;
  last_updater_id: number | null;
  update_method: string | null;
  updated_at: string | null;
  created_at: string;
}

export interface PatientFormData {
  name: string;
  age: number;
  gender: string;
  insurance_type: string;
  phone: string;
  address: string;
  emergency_contact: string;
  assigned_worker_id: number | null;
}

export interface SpecialCondition {
  id: number;
  patient_id: number;
  type: string;
  description: string;
  recorded_at: string;
}

export interface PatientVersion {
  id: number;
  patient_id: number;
  updater_id: number;
  update_method: string;
  changed_fields: string;
  created_at: string;
}
