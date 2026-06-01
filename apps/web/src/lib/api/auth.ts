import { apiClient } from "@/lib/api/client";

export type AuthResponse = {
  access_token: string;
  token_type: "bearer";
  user: {
    id: number;
    username: string;
    full_name: string;
    email: string;
    created_at: string;
  };
};

export const authApi = {
  async signin(credentials: { username_or_email: string; password: string }): Promise<AuthResponse> {
    const { data } = await apiClient.post<AuthResponse>("/auth/signin", credentials);
    return data;
  },

  async signup(userData: { username: string; full_name: string; email: string; password: string }): Promise<AuthResponse> {
    const { data } = await apiClient.post<AuthResponse>("/auth/signup", userData);
    return data;
  },
};