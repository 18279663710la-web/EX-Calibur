import { writable, derived } from 'svelte/store';
import { getStoredUser, isAuthenticated, type UserBrief } from './api';

// ---- Auth State ----
export const currentUser = writable<UserBrief | null>(getStoredUser());
export const isLoggedIn = writable<boolean>(isAuthenticated());

export function setUser(user: UserBrief | null) {
  currentUser.set(user);
  isLoggedIn.set(!!user);
}

export function logout() {
  currentUser.set(null);
  isLoggedIn.set(false);
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('user');
}

// ---- UI State ----
export const sidebarOpen = writable(false);
export const currentRoute = writable('chat');
export const mobileMenuOpen = writable(false);

export function navigate(route: string) {
  currentRoute.set(route);
  mobileMenuOpen.set(false);
  window.location.hash = `#/${route}`;
}

export function toggleSidebar() {
  sidebarOpen.update(v => !v);
}

// ---- Toast / Notifications ----
interface Toast {
  id: number;
  type: 'success' | 'error' | 'info';
  message: string;
}

let _nextId = 0;
export const toasts = writable<Toast[]>([]);

export function showToast(type: Toast['type'], message: string, duration = 4000) {
  const id = _nextId++;
  toasts.update(items => [...items, { id, type, message }]);
  setTimeout(() => {
    toasts.update(items => items.filter(t => t.id !== id));
  }, duration);
}

export function toastSuccess(msg: string) { showToast('success', msg); }
export function toastError(msg: string) { showToast('error', msg); }
export function toastInfo(msg: string) { showToast('info', msg); }

// ---- Date Helpers ----
export function formatDate(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

export function formatDateTime(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export function formatRelative(iso: string): string {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins}分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}天前`;
  return formatDate(iso);
}

export function humanBytes(bytes: number): string {
  let val = bytes;
  for (const unit of ['B', 'KB', 'MB', 'GB']) {
    if (val < 1024) return `${val.toFixed(1)} ${unit}`;
    val /= 1024;
  }
  return `${val.toFixed(1)} TB`;
}

export function humanTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}
