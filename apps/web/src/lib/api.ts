import axios from 'axios';
import { getSession } from 'next-auth/react';

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL,
  withCredentials: true,
});

// Auto-attach JWT from NextAuth session
api.interceptors.request.use(async (config) => {
  const session = await getSession();
  if (session?.accessToken) {
    config.headers.Authorization = `Bearer ${session.accessToken}`;
  }
  return config;
});

// ── Typed API helpers ─────────────────────────────────────

export const conversationsApi = {
  list: (params?: Record<string, string>) =>
    api.get('/admin/conversations', { params }),

  getThread: (id: string) =>
    api.get(`/admin/conversations/${id}/messages`),

  intercept: (id: string) =>
    api.post(`/admin/conversations/${id}/intercept`),

  reply: (id: string, text: string) =>
    api.post(`/admin/conversations/${id}/reply`, { text }),

  approveDraft: (id: string, text?: string) =>
    api.post(`/admin/conversations/${id}/approve-draft`, { text }),

  release: (id: string) =>
    api.post(`/admin/conversations/${id}/release`),

  transfer: (id: string, agentId: string) =>
    api.post(`/admin/conversations/${id}/transfer`, { agentId }),
};

export const agentsApi = {
  list:   ()                          => api.get('/admin/agents'),
  update: (id: string, data: object) => api.patch(`/admin/agents/${id}`, data),
};

export const ordersApi = {
  list: (params?: object) => api.get('/admin/orders', { params }),
};

export const catalogApi = {
  list:   ()                          => api.get('/admin/catalog'),
  update: (id: string, data: object) => api.patch(`/admin/catalog/${id}`, data),
};