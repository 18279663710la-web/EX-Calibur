<script lang="ts">
  import { currentUser, logout, toastError, toastSuccess } from '../lib/stores';
  import { kbApi, type ConversationBrief } from '../lib/api';
  import { LogOut, Plus, Search, Settings, Trash2 } from 'lucide-svelte';

  interface Props {
    onNavigate: (route: string) => void;
    onNewConversation: () => void;
    onOpenConversation: (conversationId: string) => void;
    currentRoute: string;
    activeConversationId?: string | null;
    conversationRefreshKey?: number;
  }

  let {
    onNavigate,
    onNewConversation,
    onOpenConversation,
    activeConversationId = null,
    conversationRefreshKey = 0,
  }: Props = $props();

  let conversations = $state<ConversationBrief[]>([]);
  let contextMenu = $state<{ conversationId: string; x: number; y: number } | null>(null);

  async function loadConversations() {
    try {
      const res = await kbApi.conversations(1, 50);
      if (res.data) {
        conversations = res.data.items;
      }
    } catch {
      /* keep navigation usable if history fails */
    }
  }

  $effect(() => {
    conversationRefreshKey;
    loadConversations();
  });

  function startNewConversation() {
    onNavigate('chat');
    onNewConversation();
    contextMenu = null;
  }

  function openConversation(convId: string) {
    onNavigate('chat');
    onOpenConversation(convId);
    contextMenu = null;
  }

  function openConversationMenu(e: MouseEvent, conversationId: string) {
    e.preventDefault();
    contextMenu = { conversationId, x: e.clientX, y: e.clientY };
  }

  function closeConversationMenu() {
    contextMenu = null;
  }

  function handleWindowKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      closeConversationMenu();
    }
  }

  async function deleteConversation(conversationId: string) {
    if (!confirm('确定删除该历史对话？')) {
      contextMenu = null;
      return;
    }

    try {
      await kbApi.deleteConversation(conversationId);
      conversations = conversations.filter(c => c.id !== conversationId);
      if (activeConversationId === conversationId) {
        onNewConversation();
      }
      contextMenu = null;
      toastSuccess('历史对话已删除');
    } catch {
      toastError('删除历史对话失败');
      contextMenu = null;
    }
  }

  function doLogout() {
    logout();
    onNavigate('login');
  }
</script>

<svelte:window onclick={closeConversationMenu} onkeydown={handleWindowKeydown} />

<aside class="monochrome-shell flex h-screen w-[304px] shrink-0 flex-col bg-white text-black font-[Georgia,serif]">
  <header class="sidebar-header flex shrink-0 flex-col justify-center border-b border-black px-6 py-6">
    <div class="font-mono text-xs uppercase tracking-widest text-gray-500">CloudRAG</div>
    <div class="mt-1 text-5xl font-semibold leading-none tracking-tight">CloudRAG</div>
  </header>

  <section class="sidebar-primary-actions shrink-0 border-b border-black px-5 py-6">
    <button
      onclick={startNewConversation}
      class="mb-2 flex min-h-12 w-full items-center gap-3 bg-black text-white px-4 py-3 text-left text-base font-semibold transition-colors duration-100 hover:bg-white hover:text-black hover:outline hover:outline-2 hover:outline-black focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
      type="button"
    >
      <Plus class="h-5 w-5" />
      发起新对话
    </button>

    <button
      class="flex min-h-12 w-full items-center gap-3 px-4 py-3 text-left text-base text-black transition-colors duration-100 hover:bg-black hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
      type="button"
    >
      <Search class="h-5 w-5" />
      搜索对话内容
    </button>
  </section>

  <section class="sidebar-history flex min-h-0 flex-1 flex-col overflow-y-auto border-b border-black px-5 py-6">
    <div class="mb-3 font-mono text-xs uppercase tracking-widest text-gray-500">最近</div>

    <div class="scrollbar-none min-h-0 flex-1 overflow-y-auto pr-1">
      {#each conversations as conv (conv.id)}
        <button
          onclick={() => openConversation(conv.id)}
          oncontextmenu={(e) => openConversationMenu(e, conv.id)}
          class="mb-1 w-full border-l-4 px-4 py-3 text-left text-sm transition-colors duration-100 hover:border-black hover:bg-black hover:text-white {conv.id === activeConversationId ? 'border-black bg-black text-white font-bold' : 'border-transparent bg-white text-black'}"
          type="button"
        >
          <div class="truncate">{conv.title || '新对话'}</div>
        </button>
      {/each}

      {#if conversations.length === 0}
        <p class="border-l-4 border-transparent px-4 py-5 text-sm text-gray-500">暂无历史对话</p>
      {/if}
    </div>
  </section>

  <footer class="sidebar-footer flex shrink-0 items-center gap-3 px-5 py-6">
    <div class="flex h-11 w-11 shrink-0 items-center justify-center border-2 border-black bg-black text-base font-semibold text-white">
      {$currentUser?.username?.charAt(0).toUpperCase() || 'A'}
    </div>

    <div class="min-w-0 flex-1">
      <div class="truncate text-sm font-medium">{$currentUser?.username || 'admin'}</div>
      <div class="font-mono text-xs uppercase tracking-widest text-gray-500">{$currentUser?.role === 'admin' ? '管理员账号' : '用户账号'}</div>
    </div>

    <button
      class="flex h-11 w-11 shrink-0 items-center justify-center border-2 border-black bg-white text-black transition-colors duration-100 hover:bg-black hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
      title="设置"
      type="button"
    >
      <Settings class="h-5 w-5" />
    </button>

    <button
      onclick={doLogout}
      class="flex h-11 w-11 shrink-0 items-center justify-center border-2 border-black bg-white text-black transition-colors duration-100 hover:bg-black hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
      title="退出登录"
      type="button"
    >
      <LogOut class="h-5 w-5" />
    </button>
  </footer>
</aside>

{#if contextMenu}
  <div
    class="fixed z-50 min-w-48 border-2 border-black bg-white py-1"
    style="left: {contextMenu.x}px; top: {contextMenu.y}px;"
    role="menu"
  >
    <button
      class="flex w-full items-center gap-2 px-4 py-3 text-left text-sm text-black transition-colors duration-100 hover:bg-black hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
      onclick={() => deleteConversation(contextMenu!.conversationId)}
      type="button"
    >
      <Trash2 class="h-4 w-4" />
      删除该历史对话
    </button>
  </div>
{/if}
