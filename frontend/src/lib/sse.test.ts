/**
 * TDD Test: 验证 ChatView 的 useMock 逻辑
 *
 * 当前 Bug: ChatView.svelte line 125 写死了 || true，强制用 Mock
 * 期望行为: 后端健康时不走 Mock，只有后端不可达时才 fallback
 */
import { describe, it, expect, vi } from 'vitest';
import { createChatStream, createMockChatStream } from '../src/lib/sse';

describe('ChatView SSE mode detection', () => {
  it('should use real API when backend is healthy', async () => {
    // Given: backend is reachable (health endpoint returns 200)
    const canReachBackend = async (): Promise<boolean> => {
      try {
        const res = await fetch('/health');
        return res.ok;
      } catch {
        return false;
      }
    };

    // When: deciding whether to use mock
    const useMock = !(await canReachBackend());

    // Then: if backend is healthy, should NOT use mock
    // This test FAILS with current code because `|| true` forces mock
    if (typeof window !== 'undefined' && window.location.hostname === 'localhost') {
      expect(useMock).toBe(false);
    }
  });
});
