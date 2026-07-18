export type JsonRecord = Record<string, any>;

export interface AdminProfile {
  id: number;
  username: string;
  full_name: string;
  email: string;
  roles: string[];
  permissions: string[];
  must_change_password: boolean;
  session_expires_at: string;
}

export interface SigninResponse {
  admin: AdminProfile;
  csrf_token: string;
}

export interface DangerousAction {
  title: string;
  expected: string;
  impact: string;
  execute: (confirmation: string) => Promise<void>;
}
