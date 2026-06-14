<script lang="ts">
  import { onDestroy } from 'svelte';
  import { channelsApi, type ChannelInfo, type ChannelActionResult } from '../lib/api';
  import { toastError, toastSuccess } from '../lib/stores';
  import {
    Cable,
    CheckCircle2,
    ChevronDown,
    Clock3,
    MessageCircle,
    Plus,
    RefreshCw,
    Unplug,
  } from 'lucide-svelte';

  let channels = $state<ChannelInfo[]>([]);
  let loading = $state(false);
  let qr = $state<ChannelActionResult | null>(null);
  let polling = $state(false);
  let pollTimer = $state<number | null>(null);
  let selectedChannelName = $state('');

  const primaryChannel = $derived(
    channels.find((channel) => channel.name === 'weixin') || null,
  );
  const availableChannels = $derived(
    channels.filter((channel) => channel.name !== 'weixin'),
  );

  async function loadChannels() {
    try {
      const res = await channelsApi.list();
      const nextChannels = res.data?.channels || [];
      const nextAvailable = nextChannels.filter((channel) => channel.name !== 'weixin');
      channels = nextChannels;

      if (nextChannels.some((channel) => channel.name === 'weixin' && channel.connected)) {
        qr = null;
        stopPolling();
      }

      if (!selectedChannelName && nextAvailable.length > 0) {
        selectedChannelName = nextAvailable[0].name;
      }
    } catch {
      toastError('加载通道失败');
    }
  }

  async function connectWeixin() {
    loading = true;
    try {
      const res = await channelsApi.connect('weixin');
      qr = res.data;
      await loadChannels();
      if (res.data?.status === 'connected') {
        qr = null;
        stopPolling();
        toastSuccess('微信通道已连接');
      } else {
        startPolling();
      }
    } catch {
      toastError('接入微信通道失败');
    } finally {
      loading = false;
    }
  }

  async function refreshQr() {
    try {
      const res = await channelsApi.qrLogin('refresh');
      qr = res.data;
      startPolling();
    } catch {
      toastError('刷新二维码失败');
    }
  }

  async function disconnectWeixin() {
    loading = true;
    try {
      await channelsApi.disconnect('weixin');
      stopPolling();
      qr = null;
      await loadChannels();
      toastSuccess('微信通道已断开');
    } catch {
      toastError('断开微信通道失败');
    } finally {
      loading = false;
    }
  }

  async function connectSelectedChannel() {
    if (!selectedChannelName) return;
    loading = true;
    try {
      await channelsApi.connect(selectedChannelName);
      await loadChannels();
      toastSuccess(`${selectedChannelName} 通道已接入`);
    } catch {
      toastError(`接入 ${selectedChannelName} 通道失败`);
    } finally {
      loading = false;
    }
  }

  function startPolling() {
    stopPolling();
    polling = true;
    pollTimer = window.setInterval(async () => {
      try {
        const res = await channelsApi.qrLogin('poll');
        if (res.data?.qr_status === 'confirmed') {
          qr = null;
          stopPolling();
          await loadChannels();
          toastSuccess('微信扫码登录成功');
        } else if (res.data?.qr_status === 'expired') {
          qr = res.data;
        }
      } catch {
        stopPolling();
      }
    }, 3000);
  }

  function stopPolling() {
    if (pollTimer !== null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
    polling = false;
  }

  function channelLabel(channel: ChannelInfo | null) {
    return channel?.label_i18n?.zh || channel?.label || channel?.name || '';
  }

  $effect(() => {
    loadChannels();
  });

  onDestroy(stopPolling);
</script>

<div class="h-full overflow-y-auto bg-white p-6 text-black font-[Georgia,serif] md:p-8">
  <section class="border-4 border-black bg-white p-5">
    <div class="flex flex-col justify-between gap-5 md:flex-row md:items-start">
      <div class="flex items-start gap-4">
        <div class="flex h-14 w-14 items-center justify-center border-2 border-black bg-black text-white">
          <MessageCircle class="h-6 w-6" />
        </div>
        <div>
          <div class="flex flex-wrap items-center gap-3">
            <h2 class="text-3xl font-semibold leading-none">{channelLabel(primaryChannel) || '微信'}</h2>
            {#if primaryChannel?.connected}
              <span class="inline-flex items-center gap-1 border border-black bg-black px-2 py-1 font-mono text-xs uppercase tracking-widest text-white">
                <CheckCircle2 class="h-3.5 w-3.5" />
                已连接
              </span>
            {:else if primaryChannel?.running || polling}
              <span class="inline-flex items-center gap-1 border border-black px-2 py-1 font-mono text-xs uppercase tracking-widest text-black">
                <Clock3 class="h-3.5 w-3.5" />
                等待扫码
              </span>
            {:else}
              <span class="border border-black px-2 py-1 font-mono text-xs uppercase tracking-widest text-gray-600">未接入</span>
            {/if}
          </div>
          <p class="mt-2 font-mono text-xs uppercase tracking-widest text-gray-600">weixin</p>
        </div>
      </div>

      {#if primaryChannel?.running || primaryChannel?.connected}
        <button
          class="inline-flex min-h-11 items-center gap-2 border-2 border-black bg-white px-4 py-2 font-mono text-xs uppercase tracking-widest text-black hover:bg-black hover:text-white disabled:opacity-50"
          disabled={loading}
          onclick={disconnectWeixin}
        >
          <Unplug class="h-4 w-4" />
          断开
        </button>
      {:else}
        <button
          class="inline-flex min-h-11 items-center gap-2 border-2 border-black bg-black px-4 py-2 font-mono text-xs uppercase tracking-widest text-white hover:bg-white hover:text-black disabled:opacity-50"
          disabled={loading}
          onclick={connectWeixin}
        >
          <Cable class="h-4 w-4" />
          接入
        </button>
      {/if}
    </div>

    <div class="mt-10 flex min-h-72 flex-col items-center justify-center border-t-4 border-black pt-8 text-center">
      {#if primaryChannel?.connected}
        <CheckCircle2 class="mb-4 h-12 w-12" />
        <h2 class="text-4xl font-semibold leading-none">通道已连接</h2>
        <p class="mt-3 text-sm text-gray-600">微信消息已接入 CloudRAG 工作流</p>
        <div class="mt-6 border-2 border-black bg-black px-4 py-3 text-sm text-white">
          已检测到扫码连接成功，微信消息可以正常转发并回复。
        </div>
      {:else}
        <Cable class="mb-3 h-8 w-8" />
        <h2 class="text-3xl font-semibold leading-none">微信扫码登录</h2>
        <p class="mt-2 text-sm text-gray-600">请使用微信扫描下方二维码</p>

        {#if qr?.qr_image}
          <img
            class="mt-6 h-60 w-60 border-4 border-black bg-white p-3 md:h-72 md:w-72"
            src={qr.qr_image}
            alt="微信扫码登录二维码"
          />
          <p class="mt-4 text-sm text-gray-600">
            {polling ? '等待扫码...' : '二维码轮询已停止'}
          </p>
          <p class="mt-1 font-mono text-xs uppercase tracking-widest text-gray-600">二维码约2分钟后过期</p>
          <button
            class="mt-4 inline-flex min-h-11 items-center gap-2 border-2 border-black px-3 py-2 font-mono text-xs uppercase tracking-widest text-black hover:bg-black hover:text-white"
            onclick={refreshQr}
          >
            <RefreshCw class="h-4 w-4" />
            刷新二维码
          </button>
        {:else}
          <button
            class="mt-6 inline-flex min-h-11 items-center gap-2 border-2 border-black bg-black px-4 py-2 font-mono text-xs uppercase tracking-widest text-white hover:bg-white hover:text-black disabled:opacity-50"
            disabled={loading}
            onclick={connectWeixin}
          >
            <Cable class="h-4 w-4" />
            生成二维码
          </button>
          <p class="mt-3 text-sm text-gray-600">点击后生成微信登录二维码</p>
        {/if}
      {/if}
    </div>
  </section>

  <section class="mt-6 border-4 border-black bg-white p-5">
    <div class="mb-5 flex items-center gap-3 border-b-2 border-black pb-4">
      <div class="flex h-10 w-10 items-center justify-center border-2 border-black bg-black text-white">
        <Plus class="h-5 w-5" />
      </div>
      <h2 class="text-3xl font-semibold leading-none">接入通道</h2>
    </div>

    <div class="relative">
      <select
        class="h-12 w-full appearance-none border-2 border-black bg-white px-3 pr-10 text-sm text-black outline-none transition-colors duration-100 focus:border-4"
        bind:value={selectedChannelName}
        disabled={loading || availableChannels.length === 0}
      >
        {#if availableChannels.length === 0}
          <option value="">暂无可接入通道</option>
        {:else}
          <option value="">选择要接入的通道...</option>
          {#each availableChannels as channel (channel.name)}
            <option value={channel.name}>{channelLabel(channel)} ({channel.name})</option>
          {/each}
        {/if}
      </select>
      <ChevronDown class="pointer-events-none absolute right-3 top-3 h-5 w-5 text-black" />
    </div>

    <button
      class="mt-4 inline-flex min-h-11 items-center gap-2 border-2 border-black bg-black px-4 py-2 font-mono text-xs uppercase tracking-widest text-white hover:bg-white hover:text-black disabled:opacity-50"
      disabled={loading || !selectedChannelName}
      onclick={connectSelectedChannel}
    >
      <Plus class="h-4 w-4" />
      接入选中通道
    </button>
  </section>
</div>
