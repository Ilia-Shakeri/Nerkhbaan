import { apiClient } from "@/lib/api/client";

export type AuthUser = {
  id: number;
  email: string;
  full_name: string;
};

export type AuthResponse = {
  access_token: string;
  token_type: "bearer";
  user: AuthUser;
};

export const authApi = {
  signIn: async (payload: { email: string; password: string }) => {
    const { data } = await apiClient.post<AuthResponse>("/auth/signin", payload);
    return data;
  },
  signUp: async (payload: {
    full_name: string;
    email: string;
    password: string;
    invite_code: string;
  }) => {
    const { data } = await apiClient.post<AuthResponse>("/auth/signup", payload);
    return data;
  }
};
