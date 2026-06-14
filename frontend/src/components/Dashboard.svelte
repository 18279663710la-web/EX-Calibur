<script lang="ts">
  import { toastError, humanTokens } from '../lib/stores';
  import { dashboardApi, type DashboardStats, type TimelineData, type UserStats } from '../lib/api';
  import { Chart, registerables } from 'chart.js';
  import { Zap, Users, Clock, Cpu, RefreshCw } from 'lucide-svelte';

  Chart.register(...registerables);

  function todayStr(): string {
    return new Date().toISOString().slice(0, 10);
  }

  function daysAgo(n: number): string {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d.toISOString().slice(0, 10);
  }

  let startDate = $state(daysAgo(7));
  let endDate = $state(todayStr());
  let loading = $state(true);
  let stats = $state<DashboardStats | null>(null);
  let timeline = $state<TimelineData | null>(null);
  let users = $state<UserStats[]>([]);

  let lineCanvas = $state<HTMLCanvasElement | null>(null);
  let doughnutCanvas = $state<HTMLCanvasElement | null>(null);
  let latencyCanvas = $state<HTMLCanvasElement | null>(null);
  let lineChart: Chart | null = null;
  let doughnutChart: Chart | null = null;
  let latencyChart: Chart | null = null;

  async function loadAll() {
    loading = true;
    try {
      const [s, t, u] = await Promise.all([
        dashboardApi.stats(startDate, endDate),
        dashboardApi.timeline(startDate, endDate),
        dashboardApi.userRanking(startDate, endDate, 10),
      ]);
      if (s.data) stats = s.data;
      if (t.data) timeline = t.data;
      if (u.data) users = u.data.users;
    } catch {
      toastError('加载看板数据失败');
    } finally {
      loading = false;
    }
  }

  $effect(() => { loadAll(); });

  $effect(() => {
    if (!timeline || !lineCanvas) return;
    if (lineChart) lineChart.destroy();
    lineChart = new Chart(lineCanvas, {
      type: 'line',
      data: {
        labels: timeline.series.map(p => p.date),
        datasets: [
          {
            label: '对话数',
            data: timeline.series.map(p => p.conversations),
            borderColor: '#000000',
            backgroundColor: 'rgba(0,0,0,0.04)',
            tension: 0,
            fill: true,
            yAxisID: 'y',
          },
          {
            label: 'Token(千)',
            data: timeline.series.map(p => Math.round(p.tokens_used / 1000)),
            borderColor: '#525252',
            tension: 0,
            yAxisID: 'y1',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { labels: { color: '#000000', font: { size: 11, family: 'Georgia' } } } },
        scales: {
          x: { ticks: { color: '#525252', font: { size: 10, family: 'monospace' } }, grid: { color: 'rgba(0,0,0,0.12)' } },
          y: { type: 'linear', position: 'left', ticks: { color: '#000000', font: { size: 10, family: 'monospace' } }, grid: { color: 'rgba(0,0,0,0.12)' } },
          y1: { type: 'linear', position: 'right', ticks: { color: '#525252', font: { size: 10, family: 'monospace' } }, grid: { display: false } },
        },
      },
    });
  });

  $effect(() => {
    if (!stats || !doughnutCanvas) return;
    if (doughnutChart) doughnutChart.destroy();
    doughnutChart = new Chart(doughnutCanvas, {
      type: 'doughnut',
      data: {
        labels: stats.model_breakdown.map(m => m.model),
        datasets: [{
          data: stats.model_breakdown.map(m => m.call_count),
          backgroundColor: ['#000000', '#525252', '#8a8a8a', '#c7c7c7', '#f5f5f5'],
          borderColor: '#ffffff',
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom', labels: { color: '#000000', font: { size: 10, family: 'Georgia' }, padding: 12 } } },
      },
    });
  });

  $effect(() => {
    if (!stats || !latencyCanvas) return;
    if (latencyChart) latencyChart.destroy();
    latencyChart = new Chart(latencyCanvas, {
      type: 'line',
      data: {
        labels: timeline?.series.map(p => p.date) ?? [],
        datasets: [
          { label: 'P50', data: [stats.latency.p50_latency_ms, stats.latency.p50_latency_ms], borderColor: '#000000', tension: 0 },
          { label: 'P95', data: [stats.latency.p95_latency_ms, stats.latency.p95_latency_ms], borderColor: '#525252', tension: 0 },
          { label: 'P99', data: [stats.latency.p99_latency_ms, stats.latency.p99_latency_ms], borderColor: '#8a8a8a', tension: 0 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#000000', font: { size: 10, family: 'Georgia' } } } },
        scales: {
          x: { ticks: { color: '#525252', font: { size: 10, family: 'monospace' } }, grid: { color: 'rgba(0,0,0,0.12)' } },
          y: { ticks: { color: '#525252', font: { size: 10, family: 'monospace' } }, grid: { color: 'rgba(0,0,0,0.12)' } },
        },
      },
    });
  });
</script>

<div class="h-full overflow-y-auto bg-white p-6 text-black font-[Georgia,serif] md:p-8">
  <div class="mb-6 flex flex-wrap items-center gap-2 border-b-4 border-black pb-4">
    <input type="date" bind:value={startDate} onchange={loadAll}
      class="border-2 border-black bg-white px-2 py-2 font-mono text-xs text-black" />
    <span class="font-mono text-xs uppercase tracking-widest text-gray-600">至</span>
    <input type="date" bind:value={endDate} onchange={loadAll}
      class="border-2 border-black bg-white px-2 py-2 font-mono text-xs text-black" />
    <button onclick={loadAll} class="border-2 border-black p-2 text-black hover:bg-black hover:text-white" title="刷新">
      <RefreshCw class="h-4 w-4" />
    </button>
  </div>

  {#if loading}
    <div class="flex min-h-96 items-center justify-center">
      <span class="h-8 w-8 animate-spin border-2 border-gray-300 border-t-black"></span>
    </div>
  {:else if stats}
    <div class="space-y-8">
      <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div class="border-2 border-black bg-white p-4">
          <div class="mb-2 flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-gray-600"><Zap class="h-3.5 w-3.5" /> 总对话数</div>
          <div class="text-3xl font-semibold leading-none text-black">{stats.summary.total_conversations.toLocaleString()}</div>
        </div>
        <div class="border-2 border-black bg-white p-4">
          <div class="mb-2 flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-gray-600"><Users class="h-3.5 w-3.5" /> 活跃用户</div>
          <div class="text-3xl font-semibold leading-none text-black">{stats.summary.active_users}</div>
        </div>
        <div class="border-2 border-black bg-white p-4">
          <div class="mb-2 flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-gray-600"><Cpu class="h-3.5 w-3.5" /> Token 消耗</div>
          <div class="text-3xl font-semibold leading-none text-black">{stats.token_consumption.total_tokens_human}</div>
        </div>
        <div class="border-2 border-black bg-black p-4 text-white">
          <div class="mb-2 flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-gray-300"><Clock class="h-3.5 w-3.5" /> 平均延迟</div>
          <div class="text-3xl font-semibold leading-none">{stats.latency.avg_latency_ms}ms</div>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div class="border-2 border-black bg-white p-4">
          <h3 class="mb-4 font-mono text-xs uppercase tracking-widest text-gray-600">对话 & Token 趋势</h3>
          <div class="h-64"><canvas bind:this={lineCanvas}></canvas></div>
        </div>
        <div class="border-2 border-black bg-white p-4">
          <h3 class="mb-4 font-mono text-xs uppercase tracking-widest text-gray-600">模型使用分布</h3>
          <div class="h-64"><canvas bind:this={doughnutCanvas}></canvas></div>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div class="border-2 border-black bg-white p-4">
          <h3 class="mb-4 font-mono text-xs uppercase tracking-widest text-gray-600">延迟分布 (ms)</h3>
          <div class="h-48"><canvas bind:this={latencyCanvas}></canvas></div>
        </div>

        <div class="border-2 border-black bg-white p-4">
          <h3 class="mb-3 font-mono text-xs uppercase tracking-widest text-gray-600">模型统计</h3>
          <div class="overflow-x-auto">
            <table class="w-full text-xs">
              <thead><tr class="border-b-2 border-black text-gray-600">
                <th class="py-2 text-left font-medium">模型</th>
                <th class="py-2 text-right font-medium">调用</th>
                <th class="py-2 text-right font-medium">Token</th>
                <th class="py-2 text-right font-medium">延迟</th>
              </tr></thead>
              <tbody>
                {#each stats.model_breakdown as m}
                  <tr class="border-b border-black">
                    <td class="py-2 text-black">{m.model}</td>
                    <td class="py-2 text-right text-gray-700">{m.call_count.toLocaleString()}</td>
                    <td class="py-2 text-right text-gray-700">{humanTokens(m.total_tokens)}</td>
                    <td class="py-2 text-right text-gray-700">{m.avg_latency_ms}ms</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="border-4 border-black bg-black p-4 text-white">
        <h3 class="mb-3 font-mono text-xs uppercase tracking-widest text-gray-300">费用 & 存储</h3>
        <div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div><div class="mb-1 text-xs text-gray-300">输入 Token</div><div class="text-sm font-medium">{humanTokens(stats.token_consumption.input_tokens)}</div></div>
          <div><div class="mb-1 text-xs text-gray-300">输出 Token</div><div class="text-sm font-medium">{humanTokens(stats.token_consumption.output_tokens)}</div></div>
          <div><div class="mb-1 text-xs text-gray-300">预估费用</div><div class="text-sm font-medium">${stats.token_consumption.estimated_cost_usd.toFixed(2)}</div></div>
          <div><div class="mb-1 text-xs text-gray-300">存储用量</div><div class="text-sm font-medium">{stats.summary.total_storage_human}</div></div>
        </div>
      </div>

      {#if users.length > 0}
        <div class="border-2 border-black bg-white p-4">
          <h3 class="mb-3 font-mono text-xs uppercase tracking-widest text-gray-600">用户排行榜 (Top {users.length})</h3>
          <div class="overflow-x-auto">
            <table class="w-full text-xs">
              <thead><tr class="border-b-2 border-black text-gray-600">
                <th class="py-2 text-left font-medium">用户</th>
                <th class="py-2 text-right font-medium">对话数</th>
                <th class="py-2 text-right font-medium">消息数</th>
                <th class="py-2 text-right font-medium">Token</th>
                <th class="py-2 text-right font-medium">文件数</th>
                <th class="py-2 text-right font-medium">平均延迟</th>
              </tr></thead>
              <tbody>
                {#each users as u}
                  <tr class="border-b border-black">
                    <td class="py-2"><span class="font-medium text-black">{u.username}</span><span class="ml-1 text-gray-600">{u.email}</span></td>
                    <td class="py-2 text-right text-gray-700">{u.conversations}</td>
                    <td class="py-2 text-right text-gray-700">{u.messages}</td>
                    <td class="py-2 text-right text-gray-700">{humanTokens(u.tokens_used)}</td>
                    <td class="py-2 text-right text-gray-700">{u.files_uploaded}</td>
                    <td class="py-2 text-right text-gray-700">{u.avg_latency_ms}ms</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>
