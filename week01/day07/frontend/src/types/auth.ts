export interface User {
  id: number;
  username: string;
  role: 'admin' | 'worker';
  name?: string | null;
  avatar?: string | null;
}

export interface LoginForm {
  username: string;
  password: string;
}

export interface LoginResult {
  token: string;
  user: User;
}
