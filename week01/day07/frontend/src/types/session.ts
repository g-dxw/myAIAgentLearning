export interface Session {
  id: number;
  patient_id: number;
  worker_id: number;
  status: string;
  summary?: string;
  created_at: string;
  patient_name?: string;
}

export interface ChatMessage {
  id: number;
  session_id: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export interface WorkerPatient {
  id: number;
  name: string;
  age: number;
  gender: string;
  insurance_type: string;
  guardian_info?: string;
  disease_info?: string;
  care_requirements?: string;
  personality?: string;
  info_completeness: number;
  has_ongoing_session: boolean;
}

export interface ExtractResult {
  guardian_info?: string;
  disease_info?: string;
  care_requirements?: string;
  personality?: string;
}

export interface SessionResponse {
  session: Session;
  messages: ChatMessage[];
}

export interface AddMessageResponse {
  user_message: ChatMessage;
  ai_message: ChatMessage;
}
