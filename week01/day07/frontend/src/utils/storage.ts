const TOKEN_KEY = 'token';
const USER_KEY = 'user';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function removeToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function getUser(): string | null {
  return localStorage.getItem(USER_KEY);
}

export function setUser(user: string): void {
  localStorage.setItem(USER_KEY, user);
}

export function removeUser(): void {
  localStorage.removeItem(USER_KEY);
}

export function clearAuth(): void {
  removeToken();
  removeUser();
}
