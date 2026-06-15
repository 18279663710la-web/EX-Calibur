/**
 * CloudRAG-Hub SSE 流式接收客户端
 * 实现 api-contract.md 第 5 节定义的 6 种 SSE 事件处理
 * 支持打字机效果的逐 Token 渲染
 * 成员 1 (前端架构) — 核心流式处理逻辑
 */

import type { ChatRequest, SSEMetaEvent, SSEReferencesEvent, SSEToolCallEvent, SSEErrorEvent, SSEDoneEvent } from './api';
import { getToken } from './api';

// ---- 类型 ----

export interface StreamingState {
  conversationId: string | null;
  model: string;
  content: string;            // 累积的完整文本
  references: SSEReferencesEvent | null;
  toolCalls: SSEToolCallEvent[];
  meta: SSEMetaEvent | null;
  error: SSEErrorEvent | null;
  done: SSEDoneEvent | null;
  isStreaming: boolean;
}

export type StateListener = (state: StreamingState) => void;

// ---- SSE 连接 ----

const BASE_URL = '/api/v1';

export interface ParsedSSEEvent {
  event: string;
  data: Record<string, unknown>;
}

export function parseSSEBlock(block: string): ParsedSSEEvent | null {
  let event = 'message';
  const dataLines: string[] = [];

  for (const rawLine of block.split(/\r?\n/)) {
    const line = rawLine.trimEnd();
    if (!line || line.startsWith(':')) continue;
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) as Record<string, unknown> };
  } catch {
    return null;
  }
}

export function createChatStream(
  request: ChatRequest,
  onStateChange: StateListener,
  existingState?: Partial<StreamingState>,
): { abort: () => void } {
  const abortController = new AbortController();

  const state: StreamingState = {
    conversationId: existingState?.conversationId ?? null,
    model: existingState?.model ?? request.model,
    content: existingState?.content ?? '',
    references: existingState?.references ?? null,
    toolCalls: existingState?.toolCalls ?? [],
    meta: existingState?.meta ?? null,
    error: null,
    done: null,
    isStreaming: true,
  };

  const token = getToken();
  if (!token) {
    state.error = { code: 40101, message: '未登录', conversation_id: null };
    state.isStreaming = false;
    onStateChange({ ...state });
    return { abort: () => {} };
  }

  fetch(`${BASE_URL}/knowledge-base/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
      'Accept': 'text/event-stream',
    },
    body: JSON.stringify(request),
    signal: abortController.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        state.error = {
          code: response.status,
          message: `请求失败 (HTTP ${response.status})`,
          conversation_id: state.conversationId,
        };
        state.isStreaming = false;
        onStateChange({ ...state });
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        state.error = { code: 50001, message: '浏览器不支持 ReadableStream', conversation_id: null };
        state.isStreaming = false;
        onStateChange({ ...state });
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          buffer += decoder.decode();
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() || '';

        for (const block of blocks) {
          const parsed = parseSSEBlock(block);
          if (parsed) {
            handleSSEEvent(parsed.event, parsed.data, state, onStateChange);
          }
        }
      }

      const parsed = parseSSEBlock(buffer);
      if (parsed) {
        handleSSEEvent(parsed.event, parsed.data, state, onStateChange);
      }
    })
    .catch((err) => {
      if (err.name === 'AbortError') return;
      state.error = {
        code: 50001,
        message: `网络异常: ${err.message}`,
        conversation_id: state.conversationId,
      };
      state.isStreaming = false;
      onStateChange({ ...state });
    });

  return { abort: () => abortController.abort() };
}

// ---- 事件处理 ----

function handleSSEEvent(
  eventType: string,
  data: Record<string, unknown>,
  state: StreamingState,
  onStateChange: StateListener,
): void {
  switch (eventType) {
    case 'meta': {
      const meta = data as unknown as SSEMetaEvent;
      state.meta = meta;
      state.conversationId = meta.conversation_id;
      state.model = meta.model;
      break;
    }

    case 'references': {
      state.references = data as unknown as SSEReferencesEvent;
      break;
    }

    case 'message': {
      // 逐 token 追加 —— 实现打字机效果
      const msg = data as unknown as { token: string; index: number };
      state.content += msg.token;
      break;
    }

    case 'tool_call': {
      const tc = data as unknown as SSEToolCallEvent;
      state.toolCalls = [...state.toolCalls, tc];
      break;
    }

    case 'error': {
      state.error = data as unknown as SSEErrorEvent;
      state.isStreaming = false;
      break;
    }

    case 'done': {
      state.done = data as unknown as SSEDoneEvent;
      state.conversationId = state.done.conversation_id;
      state.isStreaming = false;
      break;
    }
  }

  // 每次事件更新都通知 UI
  onStateChange({ ...state });
}

// ---- Mock SSE (前端独立开发用, 无后端时使用) ----

export function createMockChatStream(
  query: string,
  onStateChange: StateListener,
): { abort: () => void } {
  const state: StreamingState = {
    conversationId: 'mock_conv_001',
    model: 'gpt-4o',
    content: '',
    references: null,
    toolCalls: [],
    meta: null,
    error: null,
    done: null,
    isStreaming: true,
  };

  const mockResponse =
    `基于您上传的文档分析，以下是关于该主题的详细解答：\n\n` +
    `## 核心概念\n\n` +
    `首先，让我们理解基本定义。边缘计算是一种将计算和数据存储推向网络边缘的分布式计算范式，` +
    `而中心云则提供集中式的大规模计算和存储能力。\n\n` +
    `## 协作架构\n\n` +
    `边缘计算与中心云的协作可以从以下几个维度理解：\n\n` +
    `1. **数据层面**：边缘节点负责实时数据的预处理和过滤，仅将有价值的数据上传至中心云进行深度分析。\n` +
    `2. **计算层面**：时延敏感型任务在边缘执行（如自动驾驶决策），计算密集型任务在云端执行（如模型训练）。\n` +
    `3. **管理层面**：中心云负责全局调度、策略下发和模型更新，边缘节点执行本地策略。\n\n` +
    `## 关键优势\n\n` +
    `- 降低端到端延迟 60-80%\n` +
    `- 减少带宽消耗约 50%\n` +
    `- 提升数据隐私保护\n` +
    `- 增强系统整体可靠性\n\n` +
    `如果您需要针对特定场景的深入分析，请告诉我！`;

  const chars = [...mockResponse];
  let index = 0;

  // 1. meta
  state.meta = {
    conversation_id: 'mock_conv_001',
    model: 'gpt-4o',
    created_at: new Date().toISOString(),
    user_id: 'mock_user',
  };

  // 2. references
  state.references = {
    chunks: [
      {
        index: 1,
        file_id: 'file_mock_001',
        file_name: '云计算综述.pdf',
        content: '边缘计算与中心云计算的协作架构通常采用云-边-端三层模型...',
        score: 0.952,
        page_number: 12,
      },
    ],
    total_retrieved: 3,
  };

  const timer = setInterval(() => {
    if (index < chars.length) {
      // 以自然速度推送字符（中文每个字符 40-80ms，英文稍快）
      const char = chars[index];
      const delay = /[一-鿿]/.test(char) ? 60 : 30;
      state.content += char;
      index++;
      onStateChange({ ...state });
      adjustInterval(delay);
    } else {
      state.done = {
        conversation_id: 'mock_conv_001',
        message_id: 'mock_msg_001',
        usage: { prompt_tokens: 1245, completion_tokens: chars.length, total_tokens: 1245 + chars.length },
        latency_ms: 3200,
        model: 'gpt-4o',
        finished_at: new Date().toISOString(),
      };
      state.isStreaming = false;
      onStateChange({ ...state });
      clearInterval(timer);
    }
  }, 50);

  let currentTimer = timer;

  function adjustInterval(delay: number) {
    clearInterval(currentTimer);
    currentTimer = setInterval(() => {
      if (index < chars.length) {
        state.content += chars[index];
        index++;
        onStateChange({ ...state });
      } else {
        state.done = {
          conversation_id: 'mock_conv_001',
          message_id: 'mock_msg_001',
          usage: { prompt_tokens: 1245, completion_tokens: chars.length, total_tokens: 1245 + chars.length },
          latency_ms: 3200,
          model: 'gpt-4o',
          finished_at: new Date().toISOString(),
        };
        state.isStreaming = false;
        onStateChange({ ...state });
        clearInterval(currentTimer);
      }
    }, delay);
  }

  return { abort: () => clearInterval(currentTimer) };
}
