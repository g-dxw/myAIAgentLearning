import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { User } from '../types/auth';
import { getToken, setToken, setUser, clearAuth, getUser } from '../utils/storage';
import { login as loginApi, getMe } from '../services/auth';

interface AuthContextValue {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [token, setTokenState] = useState<string | null>(getToken());
  const [loading, setLoading] = useState(true);

  // 初始化：用存储的 token 验证登录状态
  useEffect(() => {
    const initAuth = async () => {
      const savedToken = getToken();
      const savedUser = getUser();
      if (savedToken && savedUser) {
        try {
          const res = await getMe();
          if (res.code === 200) {
            setUserState(res.data);
            setTokenState(savedToken);
          } else {
            clearAuth();
          }
        } catch {
          clearAuth();
        }
      }
      setLoading(false);
    };
    initAuth();
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await loginApi({ username, password });
    if (res.code !== 200) {
      throw new Error(res.message || '登录失败');
    }
    const { token: newToken, user: newUser } = res.data;
    setToken(newToken);
    setUser(JSON.stringify(newUser));
    setTokenState(newToken);
    setUserState(newUser);
  }, []);

  const logout = useCallback(() => {
    clearAuth();
    setTokenState(null);
    setUserState(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return ctx;
}
