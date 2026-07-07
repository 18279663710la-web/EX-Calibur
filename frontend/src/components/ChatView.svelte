<script lang="ts">
  import { toastError, toastInfo } from '../lib/stores';
  import { kbApi, type ChatRequest, type CloudRagFileCard, type MessageItem, type ReferenceChunk } from '../lib/api';
  import { createChatStream, normalizeCloudRagFileCards, type StreamingState } from '../lib/sse';
  import { Send, Paperclip, FileText, Bot, X, StopCircle, Download } from 'lucide-svelte';

  const MAX_CHAT_UPLOAD_FILES = 5;
  const MAX_CHAT_UPLOAD_BYTES = 15 * 1024 * 1024;
  const MAX_DAILY_CHAT_UPLOADS = 20;
  const CHAT_UPLOAD_ALLOWED_EXTENSIONS = [
    'MARKDOWN',
    'XLS',
    'PDF',
    'PROPERTIES',
    'TXT',
    'VTT',
    'MDX',
    'CSV',
    'XLSX',
    'DOCX',
    'HTML',
    'HTM',
    'MD',
  ];
  const CHAT_UPLOAD_ACCEPT = CHAT_UPLOAD_ALLOWED_EXTENSIONS.map(ext => `.${ext.toLowerCase()}`).join(',');
  const CHAT_UPLOAD_DAY_KEY = 'cloudrag_chat_upload_day';
  const CHAT_UPLOAD_COUNT_KEY = 'cloudrag_chat_upload_count';

  interface Props {
    conversationToOpen?: string | null;
    resetSignal?: number;
    onConversationChange?: (conversationId: string | null) => void;
    onConversationListChanged?: () => void;
  }

  let {
    conversationToOpen = null,
    resetSignal = 0,
    onConversationChange = () => {},
    onConversationListChanged = () => {},
  }: Props = $props();

  let query = $state('');
  let activeConvId = $state<string | null>(null);
  type ChatMessage = MessageItem & {
    files?: Array<{ id: string; original_name: string; rag_mode?: string; syncStatus?: string }>;
    fileCards?: CloudRagFileCard[];
  };
  let messages = $state<ChatMessage[]>([]);
  let loadingConv = $state(false);
  let activeAbort = $state<(() => void) | null>(null);
  let streamingState = $state<StreamingState | null>(null);
  let lastConversationToOpen = $state<string | null>(null);
  let lastResetSignal = $state<number | null>(null);

  let selectedModel = $state('deepseek-v4-flash');
  const models = ['deepseek-v4-flash'];

  let fileInput = $state<HTMLInputElement | null>(null);
  let selectedFileIds = $state<string[]>([]);
  let selectedFiles = $state<Array<{ id: string; original_name: string; rag_mode?: string }>>([]);
  let uploadProgress = $state(0);
  let uploadingFiles = $state(false);
  let uploadBlocker = $state<string | null>(null);

  $effect(() => {
    if (lastResetSignal === null) {
      lastResetSignal = resetSignal;
      return;
    }
    if (resetSignal !== lastResetSignal) {
      lastResetSignal = resetSignal;
      newConversation();
    }
  });

  $effect(() => {
    if (conversationToOpen && conversationToOpen !== activeConvId && conversationToOpen !== lastConversationToOpen) {
      lastConversationToOpen = conversationToOpen;
      openConversation(conversationToOpen);
    }
  });

  function showUploadBlocker(message: string) {
    uploadBlocker = message;
  }

  function clearUploadBlocker() {
    uploadBlocker = null;
  }

  function getTodayUploadCount() {
    const today = new Date().toISOString().slice(0, 10);
    if (localStorage.getItem(CHAT_UPLOAD_DAY_KEY) !== today) {
      localStorage.setItem(CHAT_UPLOAD_DAY_KEY, today);
      localStorage.setItem(CHAT_UPLOAD_COUNT_KEY, '0');
      return 0;
    }
    return Number(localStorage.getItem(CHAT_UPLOAD_COUNT_KEY) || '0');
  }

  function addTodayUploadCount(count: number) {
    const today = new Date().toISOString().slice(0, 10);
    const next = getTodayUploadCount() + count;
    localStorage.setItem(CHAT_UPLOAD_DAY_KEY, today);
    localStorage.setItem(CHAT_UPLOAD_COUNT_KEY, String(next));
  }

  function getExtension(file: File) {
    return (file.name.split('.').pop() || '').toUpperCase();
  }

  function validateChatFiles(files: File[]) {
    if (files.length > MAX_CHAT_UPLOAD_FILES) {
      return `每批次最多上传 ${MAX_CHAT_UPLOAD_FILES} 个文件。`;
    }
    if (getTodayUploadCount() + files.length > MAX_DAILY_CHAT_UPLOADS) {
      return `单个用户每天最多上传 ${MAX_DAILY_CHAT_UPLOADS} 个文件。`;
    }
    for (const file of files) {
      if (file.size > MAX_CHAT_UPLOAD_BYTES) {
        return `单个文件大小不得超过 15 MB：${file.name}`;
      }
      if (!CHAT_UPLOAD_ALLOWED_EXTENSIONS.includes(getExtension(file))) {
        return `文件格式不在允许上传白名单内：${file.name}`;
      }
    }
    return null;
  }

  function openNativeFilePicker() {
    clearUploadBlocker();
    fileInput?.click();
  }

  async function handleNativeFileChange(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const files = Array.from(input.files || []);
    input.value = '';
    if (files.length === 0) return;

    const validationError = validateChatFiles(files);
    if (validationError) {
      showUploadBlocker(validationError);
      return;
    }

    uploadingFiles = true;
    uploadProgress = 12;
    try {
      uploadProgress = 45;
      const res = await kbApi.uploadChatFiles(files);
      uploadProgress = 100;
      if (res.data) {
        const uploaded = res.data.items.map(item => ({
          id: item.id,
          original_name: item.original_name,
          rag_mode: item.rag_mode,
        }));
        selectedFiles = [...selectedFiles, ...uploaded];
        selectedFileIds = [...selectedFileIds, ...res.data.file_ids];
        addTodayUploadCount(files.length);
        if (res.data.status_message) {
          messages = [...messages, {
            id: 'upload_status_' + Date.now(),
            role: 'assistant',
            content: res.data.status_message,
            created_at: new Date().toISOString(),
          }];
          toastInfo(res.data.status_message);
        }
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : '文件上传失败';
      showUploadBlocker(message);
    } finally {
      setTimeout(() => {
        uploadingFiles = false;
        uploadProgress = 0;
      }, 300);
    }
  }

  function removeUploadedFile(file: { id: string; original_name: string }) {
    selectedFileIds = selectedFileIds.filter(id => id !== file.id);
    selectedFiles = selectedFiles.filter(item => item.id !== file.id);
  }

  async function openConversation(convId: string) {
    loadingConv = true;
    activeConvId = convId;
    streamingState = null;
    onConversationChange(convId);
    try {
      const res = await kbApi.conversationDetail(convId);
      if (res.data) {
        messages = res.data.messages.map(normalizeAssistantMessage);
      }
    } catch {
      toastError('加载对话失败');
    } finally {
      loadingConv = false;
    }
  }

  function newConversation() {
    activeConvId = null;
    messages = [];
    streamingState = null;
    query = '';
    selectedFileIds = [];
    selectedFiles = [];
    uploadBlocker = null;
    lastConversationToOpen = null;
    onConversationChange(null);
  }

  async function sendMessage() {
    const trimmed = query.trim();
    if (!trimmed || streamingState?.isStreaming) return;

    const selectedFileIdsSnapshot = [...selectedFileIds];
    const selectedFilesSnapshot = selectedFiles.map(file => ({
      ...file,
      syncStatus: file.rag_mode === 'ingesting' ? '向量库同步中...' : '已归档',
    }));
    const archivedFiles = selectedFilesSnapshot;
    const userMsgId = 'local_' + Date.now();
    messages = [...messages, {
      id: userMsgId,
      role: 'user',
      content: trimmed,
      files: archivedFiles,
      created_at: new Date().toISOString(),
    }];

    const userQuery = trimmed;
    query = '';
    selectedFileIds = [];
    selectedFiles = [];

    const chatReq: ChatRequest = {
      conversation_id: activeConvId,
      query: userQuery,
      file_ids: selectedFileIdsSnapshot,
      model: selectedModel,
      retrieval_config: { top_k: 5, score_threshold: 0.7, rerank_enabled: true },
    };

    const { abort } = createChatStream(
      chatReq,
      (state) => {
        streamingState = state;
        if (state.done && state.conversationId) {
          if (!activeConvId) {
            activeConvId = state.conversationId;
            onConversationChange(state.conversationId);
          }
          messages = [...messages, normalizeAssistantMessage({
            id: state.done.message_id,
            role: 'assistant',
            content: state.content,
            fileCards: state.fileCards,
            references: state.references?.chunks || null,
            usage: state.done.usage,
            latency_ms: state.done.latency_ms,
            created_at: state.done.finished_at,
          })];
          streamingState = null;
          activeAbort = null;
          onConversationListChanged();
        }
        if (state.error) {
          toastError(state.error.message);
          streamingState = null;
          activeAbort = null;
        }
      },
    );

    activeAbort = () => abort();
  }

  function stopStreaming() {
    activeAbort?.();
    streamingState = null;
    activeAbort = null;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function renderMarkdown(text: string): string {
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong class="font-bold text-black">$1</strong>');
    text = text.replace(/### (.+)/g, '<h4 class="mt-3 mb-1 text-sm font-semibold text-black">$1</h4>');
    text = text.replace(/## (.+)/g, '<h3 class="mt-4 mb-2 text-base font-semibold text-black">$1</h3>');
    text = text.replace(/- (.+)/g, '<li class="ml-4 text-black">- $1</li>');
    text = text.replace(/(\d+)\. (.+)/g, '<li class="ml-4 text-black">$1. $2</li>');
    text = text.replace(/\n\n/g, '<br><br>');
    text = text.replace(/\n/g, '<br>');
    return text;
  }

  function normalizeAssistantMessage(message: ChatMessage): ChatMessage {
    if (message.role !== 'assistant') return message;
    const normalized = normalizeCloudRagFileCards(message.content, message.fileCards || []);
    return {
      ...message,
      content: normalized.content,
      fileCards: normalized.fileCards,
    };
  }

  function formatFileSize(sizeBytes?: number | null) {
    if (!sizeBytes || sizeBytes <= 0) return '';
    if (sizeBytes < 1024) return `${sizeBytes} B`;
    if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
    return `${(sizeBytes / 1024 / 1024).toFixed(1)} MB`;
  }
</script>

<div class="gemini-chat-shell relative flex h-full min-h-0 flex-col overflow-hidden bg-white text-black font-[Georgia,serif]">
  <div class="relative z-10 min-h-0 flex-1 overflow-y-auto px-6 pb-44 pt-8 md:px-8">
    {#if loadingConv}
      <div class="flex h-full items-center justify-center">
        <span class="h-8 w-8 animate-spin border-2 border-gray-300 border-t-black"></span>
      </div>
    {:else if messages.length === 0 && !streamingState}
      <div class="mx-auto flex min-h-full max-w-5xl flex-col items-center justify-center text-center">
        <div class="mb-8 h-4 w-4 border-4 border-black"></div>
        <h1 class="mb-10 text-5xl font-semibold leading-none tracking-tight text-black md:text-7xl">需要我为你做些什么？</h1>
        <div class="h-2 w-40 bg-black"></div>
      </div>
    {:else}
      <div class="mx-auto max-w-4xl">
        {#each messages as msg (msg.id)}
          <div class="mb-8 flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
            <div class="max-w-[84%] border-2 border-black {msg.role === 'user' ? 'bg-black px-5 py-4 text-white' : 'bg-white px-5 py-4 text-black'}">
              {#if msg.role === 'assistant'}
                <div class="mb-3 flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-gray-600">
                  <Bot class="h-4 w-4" />
                  CloudRAG
                </div>
              {/if}

              {#if msg.references && msg.references.length > 0}
                <details class="mb-3 border border-black bg-white p-3 text-black">
                  <summary class="cursor-pointer font-mono text-xs uppercase tracking-widest">引用 {msg.references.length} 个片段</summary>
                  <div class="mt-2 space-y-2">
                    {#each msg.references as ref}
                      <div class="border border-black p-2 text-xs text-gray-700">
                        <div class="mb-1 flex items-center gap-2 text-black">
                          <FileText class="h-3 w-3" />
                          <span>{ref.file_name} (p.{ref.page_number})</span>
                          <span>{(ref.score * 100).toFixed(0)}%</span>
                        </div>
                        <p class="line-clamp-2">{ref.content}</p>
                      </div>
                    {/each}
                  </div>
                </details>
              {/if}

              <div class="whitespace-pre-wrap text-[16px] leading-7">
                {#if msg.role === 'assistant'}
                  {@html renderMarkdown(msg.content)}
                {:else}
                  {msg.content}
                {/if}
              </div>

              {#if msg.role === 'assistant' && msg.fileCards && msg.fileCards.length > 0}
                <div class="mt-3 flex flex-col gap-2">
                  {#each msg.fileCards as fileCard (fileCard.id)}
                    <a
                      class="flex max-w-full items-center gap-3 border-2 border-black bg-white p-3 text-black no-underline transition-none hover:bg-black hover:text-white"
                      href={fileCard.url}
                      download
                      target="_blank"
                      rel="noreferrer"
                    >
                      <FileText class="h-6 w-6 shrink-0" />
                      <span class="min-w-0 flex-1">
                        <span class="block truncate font-semibold">{fileCard.name}</span>
                        {#if formatFileSize(fileCard.sizeBytes)}
                          <span class="block font-mono text-xs uppercase tracking-widest opacity-70">{formatFileSize(fileCard.sizeBytes)}</span>
                        {/if}
                      </span>
                      <Download class="h-5 w-5 shrink-0" />
                    </a>
                  {/each}
                </div>
              {/if}

              {#if msg.files && msg.files.length > 0}
                <div class="mt-3 flex flex-col gap-2">
                  {#each msg.files as f (f.id)}
                    <div class="bg-transparent border border-black p-3 rounded-none flex items-center gap-2">
                      <FileText class="h-4 w-4 shrink-0" />
                      <span class="min-w-0 flex-1 truncate">{f.original_name}</span>
                      {#if f.syncStatus}
                        <span class="shrink-0 border-l border-current pl-2 font-mono text-xs uppercase tracking-widest">{f.syncStatus}</span>
                      {/if}
                    </div>
                  {/each}
                </div>
              {/if}

              {#if msg.usage}
                <div class="mt-3 flex gap-3 border-t border-current pt-2 font-mono text-xs uppercase tracking-widest opacity-70">
                  <span>Tokens: {msg.usage.total_tokens}</span>
                  {#if msg.latency_ms}
                    <span>耗时: {(msg.latency_ms / 1000).toFixed(2)}s</span>
                  {/if}
                </div>
              {/if}
            </div>
          </div>
        {/each}

        {#if streamingState?.isStreaming}
          <div class="mb-8 flex justify-start">
            <div class="max-w-[84%] border-2 border-black bg-white px-5 py-4 text-black">
              <div class="mb-3 flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-gray-600">
                <Bot class="h-4 w-4" />
                CloudRAG
              </div>
              <div class="whitespace-pre-wrap text-[16px] leading-7">
                {streamingState.content}<span class="cursor-blink"></span>
              </div>
              {#if streamingState.fileCards.length > 0}
                <div class="mt-3 flex flex-col gap-2">
                  {#each streamingState.fileCards as fileCard (fileCard.id)}
                    <a
                      class="flex max-w-full items-center gap-3 border-2 border-black bg-white p-3 text-black no-underline transition-none hover:bg-black hover:text-white"
                      href={fileCard.url}
                      download
                      target="_blank"
                      rel="noreferrer"
                    >
                      <FileText class="h-6 w-6 shrink-0" />
                      <span class="min-w-0 flex-1">
                        <span class="block truncate font-semibold">{fileCard.name}</span>
                        {#if formatFileSize(fileCard.sizeBytes)}
                          <span class="block font-mono text-xs uppercase tracking-widest opacity-70">{formatFileSize(fileCard.sizeBytes)}</span>
                        {/if}
                      </span>
                      <Download class="h-5 w-5 shrink-0" />
                    </a>
                  {/each}
                </div>
              {/if}
            </div>
          </div>
        {/if}
      </div>
    {/if}
  </div>

  <div class="pointer-events-none absolute inset-x-0 bottom-0 z-20 border-t-4 border-black bg-white px-6 py-5 md:px-8">
    <div class="pointer-events-auto mx-auto max-w-4xl">
      {#if uploadBlocker}
        <div class="mb-3 border-2 border-black bg-black text-white">
          <div class="border-b border-white px-4 py-2 font-mono text-xs uppercase tracking-widest">UPLOAD BLOCKED</div>
          <div class="flex items-center justify-between gap-4 px-4 py-3 text-sm">
            <span>{uploadBlocker}</span>
            <button onclick={clearUploadBlocker} class="border border-white px-2 py-1 hover:bg-white hover:text-black transition-none" type="button">
              <X class="h-4 w-4" />
            </button>
          </div>
        </div>
      {/if}

      {#if uploadingFiles}
        <div class="mb-3 border-2 border-black bg-white p-2">
          <div class="mb-2 flex justify-between font-mono text-xs uppercase tracking-widest">
            <span>Uploading</span>
            <span>{uploadProgress}%</span>
          </div>
          <div class="h-3 border border-black bg-white">
            <div class="h-full bg-black transition-none" style="width: {uploadProgress}%"></div>
          </div>
        </div>
      {/if}

      {#if selectedFiles.length > 0}
        <div class="mb-3 flex flex-col gap-2">
          {#each selectedFiles as f (f.id)}
            <div class="flex items-center justify-between gap-3 border border-black bg-white px-3 py-2 text-sm text-black">
              <div class="flex min-w-0 items-center gap-2">
                <FileText class="h-4 w-4 shrink-0" />
                <span class="truncate">文件 {f.original_name}</span>
                {#if f.rag_mode === 'ingesting'}
                  <span class="border-l border-black pl-2 font-mono text-xs uppercase tracking-widest">同步中</span>
                {/if}
              </div>
              <button onclick={() => removeUploadedFile(f)} class="shrink-0 border border-black p-1 hover:bg-black hover:text-white transition-none" type="button">
                <X class="h-3 w-3" />
              </button>
            </div>
          {/each}
        </div>
      {/if}

      <div class="gemini-compose flex min-h-[72px] items-center gap-3 border-4 border-black bg-white px-4 py-3">
        <input
          bind:this={fileInput}
          onchange={handleNativeFileChange}
          type="file"
          multiple
          accept={CHAT_UPLOAD_ACCEPT}
          class="hidden"
        />

        <button
          onclick={openNativeFilePicker}
          class="min-h-11 min-w-11 border-2 border-black p-2 text-black transition-colors duration-100 hover:bg-black hover:text-white"
          title="上传文件作为对话上下文"
          type="button"
        >
          <Paperclip class="h-5 w-5" />
        </button>

        <textarea
          bind:value={query}
          onkeydown={handleKeydown}
          placeholder="问问 CloudRAG"
          rows="1"
          class="max-h-32 min-h-10 flex-1 resize-none border-0 border-b-2 border-black bg-transparent px-1 py-2 text-lg text-black outline-none placeholder:text-gray-600 focus:border-b-4"
        ></textarea>

        <select
          bind:value={selectedModel}
          class="hidden border-0 border-b-2 border-black bg-white px-2 py-2 font-mono text-xs uppercase tracking-widest text-black outline-none hover:bg-black hover:text-white md:block"
        >
          {#each models as m}
            <option value={m}>{m}</option>
          {/each}
        </select>

        {#if streamingState?.isStreaming}
          <button
            onclick={stopStreaming}
            class="min-h-11 min-w-11 border-2 border-black bg-white p-2 text-black transition-colors duration-100 hover:bg-black hover:text-white"
            title="停止"
            type="button"
          >
            <StopCircle class="h-5 w-5" />
          </button>
        {:else}
          <button
            onclick={sendMessage}
            disabled={!query.trim()}
            class="min-h-11 min-w-11 border-2 border-black bg-black p-2 text-white transition-colors duration-100 hover:bg-white hover:text-black disabled:bg-white disabled:text-gray-500"
            title="发送"
            type="button"
          >
            <Send class="h-5 w-5" />
          </button>
        {/if}
      </div>
    </div>
  </div>
</div>
