import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, clearToken, getToken, setToken } from "../api/client";
import type { User } from "../api/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  /** Accept a token+user produced elsewhere (e.g. first-run setup). */
  adopt: (token: string, user: User) => void;
}

const AuthContext = createContext<AuthState>({
  user: null,
  loading: true,
  login: async () => {},
  logout: () => {},
  adopt: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api
      .get<User>("/auth/me")
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    const res = await api.post<{ access_token: string; user: User }>("/auth/login", {
      email,
      password,
    });
    setToken(res.access_token);
    setUser(res.user);
  };

  const logout = () => {
    clearToken();
    setUser(null);
  };

  const adopt = (token: string, u: User) => {
    setToken(token);
    setUser(u);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, adopt }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
