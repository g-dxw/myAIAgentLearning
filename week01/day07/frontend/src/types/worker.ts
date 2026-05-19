export interface Worker {
  id: number;
  user_id: number;
  name: string;
  phone: string;
  id_card: string;
  avatar: string | null;
  status: 'active' | 'inactive' | 'deleted';
  created_at: string;
}

export interface WorkerFormData {
  name: string;
  phone: string;
  id_card: string;
  avatar?: string;
}
