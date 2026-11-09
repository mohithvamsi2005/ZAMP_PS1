import { apiGet, apiPost } from './client';
import type { AuthStatus } from '../types';

export function fetchAuthStatus(): Promise<AuthStatus> {
  return apiGet<AuthStatus>('/auth/status');
}

export function loginWithPassword(password: string): Promise<AuthStatus> {
  return apiPost<AuthStatus>('/auth/login', { password });
}

export function logout(): Promise<{ authenticated: boolean }> {
  return apiPost<{ authenticated: boolean }>('/auth/logout', {});
}
