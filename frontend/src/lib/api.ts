/**
 * CloudRAG-Hub API Client
 * 严格依据 api-contract.md v1.0.0 编写
 * 成员 1 (前端架构) — 基于后端接口契约开发
 */

// ============================================================
// Types (aligned with api-contract.md)
// ============================================================

export interface Envelope<T = unknown> {
  code: number;
  message: string;
  data: T;
  meta?: {
    request_id: string;
    timestamp: string;
    latency_ms: number;
  };
}

export interface PaginatedData<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface UserBrief {
  id: string;
  username: string;
  email: string;
  avatar_url: string | null;
  role: string;
}

export interface UserProfile {
  id: string;
  username: string;
  email: string;
  avatar_url: string | null;
  role: string;
  quota_used_bytes: number;
  quota_total_bytes: number;
  created_at: string;
  last_login_at: string | null;
}

export interface LoginData {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: UserBrief;
}

export interface FileInfo {
  id: string;
  original_name: string;
  mime_type: string;
  size_bytes: number;
  size_human: string;
  tags: string[];
  description: string | null;
  folder: string;
  processing_status: 'pending' | 'processing' | 'ready' | 'failed';
  created_at: string;
}

export interface ChatUploadItem {
  id: string;
  original_name: string;
  mime_type: string;
  size_bytes: number;
  size_human: string;
  processing_status: string;
  dedup_status: string;
  rag_mode: 'ingesting' | 'standby' | 'temporary';
  matched_file_id?: string | null;
  similarity?: number;
}

export interface ChatUploadResult {
  items: ChatUploadItem[];
  file_ids: string[];
  status_message?: string | null;
}

export interface ConversationBrief {
  id: string;
  title: string | null;
  model: string;
  message_count: number;
  last_message_preview: string | null;
  total_tokens: number;
  created_at: string;
  updated_at: string;
}

export interface MessageItem {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  fileCards?: CloudRagFileCard[];
  references?: ReferenceChunk[] | null;
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number } | null;
  latency_ms?: number | null;
  created_at: string;
}

export interface CloudRagFileCard {
  id: string;
  name: string;
  url: string;
  sourceUrl?: string;
  sizeBytes?: number | null;
}

export interface ConversationDetail {
  id: string;
  title: string;
  model: string;
  messages: MessageItem[];
  created_at: string;
  updated_at: string;
}

export interface ReferenceChunk {
  index: number;
  file_id: string;
  file_name: string;
  content: string;
  score: number;
  page_number: number | null;
}

export interface DashboardStats {
  summary: {
    total_conversations: number;
    total_messages: number;
    total_files_uploaded: number;
    total_storage_bytes: number;
    total_storage_human: string;
    active_users: number;
  };
  token_consumption: {
    total_tokens: number;
    total_tokens_human: string;
    input_tokens: number;
    output_tokens: number;
    avg_tokens_per_conversation: number;
    estimated_cost_usd: number;
  };
  latency: {
    avg_latency_ms: number;
    p50_latency_ms: number;
    p95_latency_ms: number;
    p99_latency_ms: number;
    max_latency_ms: number;
    min_latency_ms: number;
  };
  model_breakdown: Array<{
    model: string;
    call_count: number;
    total_tokens: number;
    avg_latency_ms: number;
  }>;
  period: { start_date: string; end_date: string };
}

export interface TimelinePoint {
  date: string;
  conversations: number;
  messages: number;
  tokens_used: number;
  avg_latency_ms: number;
  files_uploaded: number;
  active_users: number;
  errors_count: number;
}

export interface TimelineData {
  granularity: string;
  series: TimelinePoint[];
  period: { start_date: string; end_date: string };
}

export interface ChannelInfo {
  name: string;
  label: string;
  label_i18n?: Record<string, string>;
  icon?: string;
  color?: string;
  running: boolean;
  connected: boolean;
  active?: boolean;
  status: string;
  login_status?: string;
  fields?: Array<Record<string, unknown>>;
  description?: string;
}

export interface ChannelActionResult {
  status: string;
  message?: string;
  qrcode_url?: string;
  qr_image?: string;
  qr_status?: string;
  bot_id?: string;
}

export interface UserStats {
  user_id: string;
  username: string;
  email: string;
  conversations: number;
  messages: number;
  tokens_used: number;
  files_uploaded: number;
  avg_latency_ms: number;
  last_active_at: string | null;
}

export interface ChatRequest {
  conversation_id: string | null;
  query: string;
  file_ids: string[];
  model: string;
  retrieval_config?: {
    top_k: number;
    score_threshold: number;
    rerank_enabled: boolean;
  };
  system_prompt_override?: string | null;
}

// SSE event types
export interface SSEMetaEvent {
  conversation_id: string;
  model: string;
  created_at: string;
  user_id: string;
}

export interface SSEReferencesEvent {
  chunks: ReferenceChunk[];
  total_retrieved: number;
}

export interface SSEMessageToken {
  token: string;
  index: number;
}

export interface SSEToolCallEvent {
  tool_name: string;
  status: 'calling' | 'completed';
  input: Record<string, unknown> | null;
  output?: string | null;
  duration_ms?: number | null;
  timestamp: string;
}

export interface SSEErrorEvent {
  code: number;
  message: string;
  conversation_id: string | null;
}

export interface SSEDoneEvent {
  conversation_id: string;
  message_id: string;
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  latency_ms: number;
  model: string;
  finished_at: string;
}

// ============================================================
// HTTP Client
// ============================================================

const BASE_URL = '/api/v1';

class ApiError extends Error {
  code: number;
  constructor(code: number, message: string) {
    super(message);
    this.code = code;
    this.name = 'ApiError';
  }
}

export function getToken(): string | null {
  return localStorage.getItem('access_token');
}

function getRefreshToken(): string | null {
  return localStorage.getItem('refresh_token');
}

async function request<T>(
  endpoint: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> || {}),
  };

  if (token && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  // Don't set Content-Type for FormData (browser sets it with boundary)
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json';
  }

  const res = await fetch(`${BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (res.status === 401 && getRefreshToken()) {
    // Attempt token refresh
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      headers['Authorization'] = `Bearer ${getToken()}`;
      const retryRes = await fetch(`${BASE_URL}${endpoint}`, {
        ...options,
        headers,
      });
      if (!retryRes.ok) {
        const err = await retryRes.json().catch(() => ({}));
        throw new ApiError(retryRes.status, err.message || retryRes.statusText);
      }
      return retryRes.json();
    }
    // Refresh failed — clear and let user re-login
    clearAuth();
    window.location.hash = '#/login';
    throw new ApiError(401, '登录已过期');
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new ApiError(res.status, err.message || res.statusText);
  }

  return res.json();
}

async function refreshAccessToken(): Promise<boolean> {
  const refresh = getRefreshToken();
  if (!refresh) return false;
  try {
    const res = await fetch(`${BASE_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) return false;
    const body = await res.json();
    if (body.data) {
      localStorage.setItem('access_token', body.data.access_token);
      localStorage.setItem('refresh_token', body.data.refresh_token);
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

// ============================================================
// Auth API
// ============================================================

export const authApi = {
  register: (body: {
    username: string;
    email: string;
    password: string;
    confirm_password: string;
  }) =>
    request<Envelope<UserBrief>>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  login: (body: { username: string; password: string }) =>
    request<Envelope<LoginData>>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  me: () => request<Envelope<UserProfile>>('/auth/me'),

  refresh: (refresh_token: string) =>
    request<Envelope<{ access_token: string; refresh_token: string; token_type: string; expires_in: number }>>(
      '/auth/refresh',
      { method: 'POST', body: JSON.stringify({ refresh_token }) },
    ),
};

// ============================================================
// Files API
// ============================================================

export const filesApi = {
  upload: (file: File, tags?: string, description?: string, folder?: string, chunkSeparator?: string, chunkMaxLength?: number, chunkOverlap?: number) => {
    const form = new FormData();
    form.append('file', file);
    if (tags) form.append('tags', tags);
    if (description) form.append('description', description);
    if (folder) form.append('folder', folder);
    if (chunkSeparator) form.append('chunk_separator', chunkSeparator);
    if (chunkMaxLength !== undefined) form.append('chunk_max_length', String(chunkMaxLength));
    if (chunkOverlap !== undefined) form.append('chunk_overlap', String(chunkOverlap));
    return request<Envelope<FileInfo & { url: string; stored_name: string }>>('/files/upload', {
      method: 'POST',
      body: form,
    });
  },

  list: (params?: {
    page?: number;
    page_size?: number;
    keyword?: string;
    status?: string;
    mime_type?: string;
    folder?: string;
    sort_by?: string;
    order?: string;
  }) => {
    const qs = new URLSearchParams();
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined) qs.set(k, String(v));
      });
    }
    return request<Envelope<PaginatedData<FileInfo>>>(`/files?${qs}`);
  },

  delete: (fileId: string) =>
    request<Envelope<{ id: string; deleted_at: string }>>(`/files/${fileId}`, {
      method: 'DELETE',
    }),

  syncFromDify: () =>
    request<Envelope<{ synced: number; deleted: number; message: string }>>('/files/sync-from-dify', {
      method: 'POST',
    }),

  downloadUrl: (fileId: string) => `${BASE_URL}/files/${fileId}/download`,
};

// ============================================================
// Dashboard API (admin only)
// ============================================================

export const dashboardApi = {
  stats: (startDate: string, endDate: string) =>
    request<Envelope<DashboardStats>>(
      `/dashboard/stats?start_date=${startDate}&end_date=${endDate}`,
    ),

  timeline: (startDate: string, endDate: string, granularity = 'daily') =>
    request<Envelope<TimelineData>>(
      `/dashboard/stats/timeline?start_date=${startDate}&end_date=${endDate}&granularity=${granularity}`,
    ),

  userRanking: (startDate: string, endDate: string, limit = 10, sortBy = 'tokens_used') =>
    request<Envelope<{ users: UserStats[] }>>(
      `/dashboard/stats/users?start_date=${startDate}&end_date=${endDate}&limit=${limit}&sort_by=${sortBy}`,
    ),
};

// ============================================================
// Knowledge Base API
// ============================================================

export const kbApi = {
  conversations: (page = 1, pageSize = 20) =>
    request<Envelope<PaginatedData<ConversationBrief>>>(
      `/knowledge-base/conversations?page=${page}&page_size=${pageSize}`,
    ),

  conversationDetail: (id: string) =>
    request<Envelope<ConversationDetail>>(`/knowledge-base/conversations/${id}`),

  deleteConversation: (id: string) =>
    request<Envelope<{ id: string; deleted: boolean }>>(`/knowledge-base/conversations/${id}`, {
      method: 'DELETE',
    }),

  uploadChatFiles: (files: File[]) => {
    const form = new FormData();
    files.forEach(file => form.append('files', file));
    return request<Envelope<ChatUploadResult>>('/knowledge-base/chat/upload', {
      method: 'POST',
      body: form,
    });
  },
};

// ============================================================
// Channels API
// ============================================================

export const channelsApi = {
  list: () => request<Envelope<{ channels: ChannelInfo[] }>>('/channels'),

  connect: (channel: string, config?: Record<string, unknown>) =>
    request<Envelope<ChannelActionResult>>('/channels', {
      method: 'POST',
      body: JSON.stringify({ channel, action: 'connect', config }),
    }),

  disconnect: (channel: string) =>
    request<Envelope<ChannelActionResult>>('/channels', {
      method: 'POST',
      body: JSON.stringify({ channel, action: 'disconnect' }),
    }),

  qrLogin: (action: 'fetch' | 'poll' | 'refresh' = 'fetch') =>
    request<Envelope<ChannelActionResult>>('/channels/weixin/qrlogin', {
      method: 'POST',
      body: JSON.stringify({ action }),
    }),
};

// ============================================================
// Auth helpers
// ============================================================

export function saveAuth(loginData: LoginData): void {
  localStorage.setItem('access_token', loginData.access_token);
  localStorage.setItem('refresh_token', loginData.refresh_token);
  localStorage.setItem('user', JSON.stringify(loginData.user));
}

export function clearAuth(): void {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('user');
}

export function getStoredUser(): UserBrief | null {
  try {
    const raw = localStorage.getItem('user');
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

export function isAdmin(): boolean {
  const user = getStoredUser();
  return user?.role === 'admin';
}

export { ApiError };
