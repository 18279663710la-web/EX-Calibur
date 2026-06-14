<script lang="ts">
  import { Cable, LayoutDashboard } from 'lucide-svelte';
  import Sidebar from './Sidebar.svelte';

  interface Props {
    currentRoute: string;
    pageTitle: string;
    activeConversationId?: string | null;
    conversationRefreshKey?: number;
    onNavigate: (route: string) => void;
    onNewConversation: () => void;
    onOpenConversation: (conversationId: string) => void;
    children?: import('svelte').Snippet;
  }

  let {
    currentRoute,
    pageTitle,
    activeConversationId = null,
    conversationRefreshKey = 0,
    onNavigate,
    onNewConversation,
    onOpenConversation,
    children,
  }: Props = $props();
</script>

<div
  class="monochrome-shell flex h-dvh w-full overflow-hidden bg-white text-black font-[Georgia,serif]"
  style="background-image: repeating-linear-gradient(0deg, transparent, transparent 1px, rgba(0,0,0,0.018) 1px, rgba(0,0,0,0.018) 2px); background-size: 100% 4px;"
>
  <Sidebar
    {currentRoute}
    {activeConversationId}
    {conversationRefreshKey}
    {onNavigate}
    {onNewConversation}
    {onOpenConversation}
  />

  <section class="app-main-frame flex min-w-0 flex-1 flex-col border-l-4 border-black bg-white">
    <header class="app-topbar flex min-h-20 items-center justify-between border-b-4 border-black bg-white px-6">
      <div class="font-mono text-xs uppercase tracking-widest text-gray-600">{pageTitle}</div>

      <div class="topbar-actions flex gap-4">
        <button
          onclick={() => onNavigate('channels')}
          class="flex items-center gap-2 border border-black px-4 py-2 text-sm font-medium text-black hover:bg-black hover:text-white transition-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          type="button"
        >
          <Cable class="h-4 w-4" />
          通道管理
        </button>

        <button
          onclick={() => onNavigate('dashboard')}
          class="flex items-center gap-2 border border-black px-4 py-2 text-sm font-medium text-black hover:bg-black hover:text-white transition-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          type="button"
        >
          <LayoutDashboard class="h-4 w-4" />
          数据看板
        </button>
      </div>
    </header>

    <main class="app-content-frame min-h-0 flex-1 overflow-hidden border-4 border-black border-l-0 border-t-0 bg-white">
      {@render children?.()}
    </main>
  </section>
</div>
