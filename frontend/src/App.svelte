<script lang="ts">
  import { isLoggedIn } from './lib/stores';
  import { isAuthenticated, isAdmin } from './lib/api';
  import Toast from './components/Toast.svelte';
  import AppLayout from './components/AppLayout.svelte';
  import Login from './components/Login.svelte';
  import ChatView from './components/ChatView.svelte';
  import Dashboard from './components/Dashboard.svelte';
  import ChannelManager from './components/ChannelManager.svelte';

  let currentRoute = $state('chat');
  let activeConversationId = $state<string | null>(null);
  let conversationToOpen = $state<string | null>(null);
  let chatResetSignal = $state(0);
  let conversationRefreshKey = $state(0);

  const pageTitle = $derived(
    currentRoute === 'channels'
      ? '管理 / 通道'
      : currentRoute === 'dashboard'
        ? '数据看板'
        : 'KNOWLEDGE CONVERSATION',
  );

  function navigate(route: string) {
    currentRoute = route;
    window.location.hash = `#/${route}`;
  }

  function syncRoute() {
    const hash = window.location.hash.replace('#/', '') || 'chat';
    if (!isAuthenticated() && hash !== 'login' && hash !== 'register') {
      currentRoute = 'login';
      window.location.hash = '#/login';
      return;
    }
    currentRoute = hash;
  }

  $effect(() => {
    syncRoute();
    window.addEventListener('hashchange', syncRoute);
    return () => window.removeEventListener('hashchange', syncRoute);
  });

  $effect(() => {
    if (!$isLoggedIn && currentRoute !== 'register') {
      currentRoute = 'login';
      window.location.hash = '#/login';
    }
  });

  function startNewConversation() {
    activeConversationId = null;
    conversationToOpen = null;
    chatResetSignal += 1;
    navigate('chat');
  }

  function openConversation(conversationId: string) {
    activeConversationId = conversationId;
    conversationToOpen = conversationId;
    navigate('chat');
  }

  function handleConversationChange(conversationId: string | null) {
    activeConversationId = conversationId;
  }

  function refreshConversations() {
    conversationRefreshKey += 1;
  }
</script>

<Toast />

{#if currentRoute === 'login' || currentRoute === 'register'}
  <Login isRegister={currentRoute === 'register'} />
{:else}
  <AppLayout
    currentRoute={currentRoute}
    pageTitle={pageTitle}
    activeConversationId={activeConversationId}
    conversationRefreshKey={conversationRefreshKey}
    onNavigate={navigate}
    onNewConversation={startNewConversation}
    onOpenConversation={openConversation}
  >
    {#if currentRoute === 'dashboard' && isAdmin()}
      <Dashboard />
    {:else if currentRoute === 'channels'}
      <ChannelManager />
    {:else}
      <ChatView
        conversationToOpen={conversationToOpen}
        resetSignal={chatResetSignal}
        onConversationChange={handleConversationChange}
        onConversationListChanged={refreshConversations}
      />
    {/if}
  </AppLayout>
{/if}
