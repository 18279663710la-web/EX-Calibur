<script lang="ts">
  import { isAdmin } from '../lib/api';
  import { MessageCircle, LayoutDashboard, Cable } from 'lucide-svelte';

  interface Props {
    onNavigate: (route: string) => void;
    currentRoute: string;
  }

  let { onNavigate, currentRoute }: Props = $props();

  const navItems = [
    { id: 'chat', label: '对话', icon: MessageCircle },
    { id: 'channels', label: '通道', icon: Cable },
    { id: 'dashboard', label: '看板', icon: LayoutDashboard, adminOnly: true },
  ];
</script>

<nav class="monochrome-shell fixed bottom-0 left-0 right-0 z-40 border-t-4 border-black bg-white text-black safe-bottom font-[Georgia,serif]">
  <div class="mx-auto flex h-16 max-w-lg items-center justify-around">
    {#each navItems as item}
      {#if !item.adminOnly || isAdmin()}
        <button
          onclick={() => onNavigate(item.id)}
          class="flex min-h-11 flex-col items-center gap-1 border border-black px-4 py-2 text-xs transition-colors duration-100
            {currentRoute === item.id ? 'bg-black text-white' : 'bg-white text-black'}"
        >
          <item.icon class="h-5 w-5" />
          <span>{item.label}</span>
        </button>
      {/if}
    {/each}
  </div>
</nav>
