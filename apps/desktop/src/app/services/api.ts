import axios from 'axios';

// Ensure the base URL correctly points to the API gateway
const baseURL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api';

export const apiInstance = axios.create({
  baseURL,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiInstance.interceptors.request.use((config) => {
  const token = localStorage.getItem('authToken');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiInstance.interceptors.response.use(
  (response) => response,
  async (error) => {
    // Enhanced error logging to help debug 'failed to fetch'
    console.error('API Error:', error.response?.data || error.message);
    
    let message = error.message || 'An unexpected error occurred.';
    if (error.response) {
      if (error.response.status === 401) {
        window.dispatchEvent(new Event('auth-expired'));
      }
      try {
        const body = error.response.data;
        if (body?.detail) {
          if (typeof body.detail === 'string') {
            message = body.detail;
          } else if (Array.isArray(body.detail)) {
            message = body.detail.map((err: any) => `${err.loc[err.loc.length - 1]}: ${err.msg}`).join(', ');
          }
        }
      } catch {
        // Fallback to error message
      }
    }
    throw new Error(message);
  }
);

export type AuthResponse = {
  access_token: string;
  token_type: 'bearer';
  user: {
    id: number;
    username: string;
    full_name: string;
    email: string;
    created_at: string;
  };
};

export const api = {
  auth: {
    async signin(credentials: { username_or_email: string; password: string }): Promise<AuthResponse> {
      const { data } = await apiInstance.post<AuthResponse>('/auth/signin', credentials);
      return data;
    },
    async signup(userData: { username: string; full_name: string; email: string; password: string }): Promise<AuthResponse> {
      const { data } = await apiInstance.post<AuthResponse>('/auth/signup', userData);
      return data;
    },
    async forgotPassword(email: string): Promise<void> {
        await apiInstance.post('/auth/forgot-password', { email });
    }
  }
};