<script lang="ts">
  import { toasts } from '../lib/stores';
</script>

{#if $toasts.length > 0}
  <div class="fixed top-4 right-4 z-50 flex flex-col gap-2 max-w-sm safe-top">
    {#each $toasts as item (item.id)}
      <div
        class="px-4 py-3 rounded-lg shadow-lg text-sm font-medium animate-slide-in
          {item.type === 'success' ? 'bg-emerald-600 text-white' : ''}
          {item.type === 'error' ? 'bg-red-600 text-white' : ''}
          {item.type === 'info' ? 'bg-sky-600 text-white' : ''}"
        role="alert"
      >
        {item.message}
      </div>
    {/each}
  </div>
{/if}

<style>
  @keyframes slide-in {
    from { opacity: 0; transform: translateX(100%); }
    to { opacity: 1; transform: translateX(0); }
  }
  .animate-slide-in { animation: slide-in 0.25s ease-out; }
</style>
