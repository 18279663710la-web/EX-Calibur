<script lang="ts">
  import { toastSuccess, toastError, humanBytes, formatDateTime } from '../lib/stores';
  import { filesApi, type FileInfo } from '../lib/api';
  import {
    Upload, FileText, FileImage, FileSpreadsheet, File, Trash2, Search,
    X, Download, Check, Clock, AlertTriangle, Loader, FolderOpen,
    Settings, ChevronDown, ChevronRight,
  } from 'lucide-svelte';

  let files = $state<FileInfo[]>([]);
  let loading = $state(true);
  let uploading = $state(false);
  let uploadProgress = $state(0);
  let uploadFolderMode = $state(false);
  let keyword = $state('');
  let statusFilter = $state('');
  let folderFilter = $state('');
  let uploadFolder = $state('');
  let page = $state(1);

  // Segmentation/chunking settings (aligned with Dify)
  let showSegSettings = $state(false);
  let chunkSeparator = $state('\n\n');
  let chunkMaxLength = $state(500);
  let chunkOverlap = $state(50);
  let total = $state(0);
  let totalPages = $state(1);
  let dropActive = $state(false);
  const MAX_FILES_PER_BATCH = 5;
  const MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024;
  const DIFY_SYNC_POLL_MS = 5000;

  async function loadFiles() {
    loading = true;
    try {
      const res = await filesApi.list({
        page,
        page_size: 20,
        keyword: keyword || undefined,
        status: statusFilter || undefined,
        folder: folderFilter || undefined,
      });
      if (res.data) {
        files = res.data.items;
        total = res.data.total;
        totalPages = res.data.total_pages;
      }
    } catch (err: unknown) {
      const e = err as { message?: string; code?: number };
      toastError(e?.message || '加载文件列表失败');
    } finally {
      loading = false;
    }
  }

  // Keep CloudRAG and Dify visibly aligned while this page is open.
  let _autoRefreshTimer: ReturnType<typeof setInterval> | null = null;
  $effect(() => {
    _autoRefreshTimer = setInterval(() => {
      filesApi.syncFromDify().catch(() => {}).finally(() => loadFiles());
    }, DIFY_SYNC_POLL_MS);
    return () => { if (_autoRefreshTimer) { clearInterval(_autoRefreshTimer); _autoRefreshTimer = null; } };
  });

  $effect(() => {
    loadFiles();
    // 首次加载时从 Dify 同步文件列表
    filesApi.syncFromDify().then(() => loadFiles());
  });

  function onSearch() {
    page = 1;
    loadFiles();
  }

  async function batchUpload(files: FileList | File[]) {
    const fileArray = Array.from(files);
    if (fileArray.length === 0) return;
    if (fileArray.length > MAX_FILES_PER_BATCH) {
      toastError(`单批最多上传 ${MAX_FILES_PER_BATCH} 个文件`);
      return;
    }

    const oversized = fileArray.find(file => file.size > MAX_FILE_SIZE_BYTES);
    if (oversized) {
      toastError(`单文件最大 15MB: ${oversized.name}`);
      return;
    }

    uploading = true;
    uploadProgress = 0;
    let done = 0;
    let failed = 0;
    const total = fileArray.length;

    for (const file of fileArray) {
      try {
        await filesApi.upload(file, '', '', uploadFolder, chunkSeparator, chunkMaxLength, chunkOverlap);
        done++;
      } catch {
        failed++;
      }
      uploadProgress = Math.round(((done + failed) / total) * 100);
    }

    uploading = false;
    uploadFolderMode = false;
    if (done > 0) toastSuccess(`成功上传 ${done} 个文件` + (failed > 0 ? `，${failed} 个失败` : ''));
    else toastError('上传失败');

    loadFiles();
  }

  function handleUpload(e: Event) {
    const input = e.target as HTMLInputElement;
    if (!input.files || input.files.length === 0) return;
    batchUpload(input.files);
    input.value = '';
  }

  async function handleDelete(fileId: string, name: string) {
    if (!confirm(`确定删除 "${name}"？`)) return;
    try {
      await filesApi.delete(fileId);
      toastSuccess('文件已删除');
      loadFiles();
    } catch {
      toastError('删除失败');
    }
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    dropActive = false;
    if (!e.dataTransfer?.files || e.dataTransfer.files.length === 0) return;
    batchUpload(e.dataTransfer.files);
  }

  function getFileIcon(mime: string) {
    if (mime.startsWith('image/')) return FileImage;
    if (mime.includes('spreadsheet') || mime.includes('excel') || mime === 'text/csv') return FileSpreadsheet;
    if (mime.includes('pdf') || mime.includes('document') || mime.includes('word') || mime.includes('text/')) return FileText;
    return File;
  }

  function getStatusBadge(status: string) {
    switch (status) {
      case 'ready': return { label: '就绪', class: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30', icon: Check };
      case 'processing': return { label: '处理中', class: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30', icon: Loader };
      case 'pending': return { label: '等待中', class: 'bg-gray-500/10 text-gray-400 border-gray-500/30', icon: Clock };
      case 'failed': return { label: '失败', class: 'bg-red-500/10 text-red-400 border-red-500/30', icon: AlertTriangle };
      default: return { label: status, class: 'bg-gray-500/10 text-gray-400', icon: Check };
    }
  }
</script>

<div class="flex flex-col h-full">
  <!-- Header -->
  <div class="h-14 flex items-center justify-between px-4 border-b border-gray-800 bg-gray-900/50">
    <h2 class="text-sm font-medium text-gray-200">文件管理</h2>
    <span class="text-xs text-gray-600">{total} 个文件</span>
  </div>

  <!-- Search & Filter bar -->
  <div class="px-4 py-3 border-b border-gray-800 flex flex-col sm:flex-row gap-2">
    <div class="flex-1 relative">
      <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
      <input
        type="text"
        bind:value={keyword}
        onkeydown={(e) => e.key === 'Enter' && onSearch()}
        placeholder="搜索文件名或文件夹..."
        class="w-full pl-9 pr-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200
               placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
      />
    </div>
    <select
      bind:value={statusFilter}
      onchange={() => { page = 1; loadFiles(); }}
      class="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-300
             focus:outline-none focus:ring-1 focus:ring-sky-500"
    >
      <option value="">全部状态</option>
      <option value="ready">就绪</option>
      <option value="processing">处理中</option>
      <option value="pending">等待中</option>
      <option value="failed">失败</option>
    </select>

    <!-- Segmentation settings toggle -->
    <button
      onclick={() => showSegSettings = !showSegSettings}
      class="flex items-center gap-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-xs text-gray-400
             hover:text-gray-200 hover:border-gray-600 transition-colors"
      title="文本分段设置（与Dify对齐）"
    >
      <Settings class="w-3.5 h-3.5" />
      分段设置
      {#if showSegSettings}
        <ChevronDown class="w-3.5 h-3.5" />
      {:else}
        <ChevronRight class="w-3.5 h-3.5" />
      {/if}
    </button>
  </div>

  <!-- Segmentation settings panel -->
  {#if showSegSettings}
    <div class="px-4 py-3 border-b border-gray-800 bg-gray-900/50 grid grid-cols-1 sm:grid-cols-3 gap-3">
      <div>
        <label for="chunk-separator" class="block text-xs text-gray-500 mb-1">分段标识符</label>
        <select
          id="chunk-separator"
          bind:value={chunkSeparator}
          class="w-full px-2.5 py-1.5 bg-gray-800 border border-gray-700 rounded text-xs text-gray-300
                 focus:outline-none focus:ring-1 focus:ring-sky-500"
        >
          <option value={'\n\n'}>\\n\\n（段落分隔）</option>
          <option value={'\n'}>\\n（换行分隔）</option>
          <option value={'。'}>。（句号分隔）</option>
          <option value={'. '}>. （英文句号）</option>
          <option value={'；'}>；（分号分隔）</option>
          <option value={'\n\n\n'}>{'\\n\\n\\n（大段分隔）'}</option>
        </select>
      </div>
      <div>
        <label for="chunk-max-length" class="block text-xs text-gray-500 mb-1">分段最大长度: {chunkMaxLength}</label>
        <input
          id="chunk-max-length"
          type="range" min="100" max="2000" step="50"
          bind:value={chunkMaxLength}
          class="w-full accent-sky-500"
        />
      </div>
      <div>
        <label for="chunk-overlap" class="block text-xs text-gray-500 mb-1">分段重叠长度: {chunkOverlap}</label>
        <input
          id="chunk-overlap"
          type="range" min="0" max="200" step="10"
          bind:value={chunkOverlap}
          class="w-full accent-sky-500"
        />
      </div>
    </div>
  {/if}

  <div class="px-4 py-3 border-b border-gray-800 flex flex-col sm:flex-row gap-2">
    <input
      type="text"
      bind:value={uploadFolder}
      placeholder="输入文件夹名（可选）"
      class="w-40 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-xs text-gray-300
             placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
      maxlength="200"
    />
    <label class="flex items-center justify-center gap-2 px-4 py-2 bg-gradient-to-r from-sky-500 to-violet-500
                   rounded-lg text-sm font-medium text-white cursor-pointer hover:from-sky-400 hover:to-violet-400
                   transition-all shrink-0 {uploading ? 'opacity-50 pointer-events-none' : ''}">
      {#if uploading && !uploadFolderMode}
        <span class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
        上传中 ({uploadProgress}%)
      {:else}
        <Upload class="w-4 h-4" />
        上传文件
      {/if}
      <input type="file" onchange={handleUpload} class="hidden" multiple accept=".pdf,.docx,.doc,.txt,.md,.csv,.xlsx,.pptx,.png,.jpg,.jpeg,.gif" />
    </label>
    <label class="flex items-center justify-center gap-2 px-4 py-2 bg-gradient-to-r from-violet-500 to-fuchsia-500
                   rounded-lg text-sm font-medium text-white cursor-pointer hover:from-violet-400 hover:to-fuchsia-400
                   transition-all shrink-0 {uploading ? 'opacity-50 pointer-events-none' : ''}">
      {#if uploading && uploadFolderMode}
        <span class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
        上传中 ({uploadProgress}%)
      {:else}
        <FolderOpen class="w-4 h-4" />
        上传文件夹
      {/if}
      <input type="file" onchange={(e) => { uploadFolderMode = true; handleUpload(e); }} class="hidden" webkitdirectory multiple />
    </label>
  </div>

  <!-- Drop zone overlay -->
  {#if dropActive}
    <div
      role="presentation"
      class="absolute inset-0 bg-sky-500/10 border-2 border-dashed border-sky-500 rounded-xl flex items-center justify-center z-10"
      ondragover={(e) => { e.preventDefault(); dropActive = true; }}
      ondragleave={() => dropActive = false}
      ondrop={handleDrop}
    >
      <div class="text-center">
        <Upload class="w-10 h-10 text-sky-400 mx-auto mb-2" />
        <p class="text-sm text-sky-400 font-medium">释放文件以上传</p>
        <p class="text-xs text-gray-500 mt-1">支持 PDF, Word, Markdown, 图片等</p>
      </div>
    </div>
  {/if}

  <!-- File grid -->
  <div class="flex-1 overflow-y-auto p-4">
    {#if loading}
      <div class="flex justify-center py-20">
        <span class="w-6 h-6 border-2 border-gray-600 border-t-sky-400 rounded-full animate-spin"></span>
      </div>
    {:else if files.length === 0}
      <div class="text-center py-20">
        <FileText class="w-12 h-12 text-gray-700 mx-auto mb-3" />
        <p class="text-sm text-gray-600">
          {keyword || statusFilter ? '没有匹配的文件' : '还没有上传任何文件'}
        </p>
        <p class="text-xs text-gray-700 mt-1">拖拽文件到此处或点击上传按钮</p>
      </div>
    {:else}
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {#each files as f (f.id)}
          {@const IconComponent = getFileIcon(f.mime_type)}
          {@const badge = getStatusBadge(f.processing_status)}
          <div class="bg-gray-900 rounded-xl border border-gray-800 p-4 hover:border-gray-700 transition-colors group">
            <div class="flex items-start justify-between mb-3">
              <div class="w-10 h-10 rounded-lg bg-gray-800 flex items-center justify-center">
                <IconComponent class="w-5 h-5 text-gray-400" />
              </div>
              <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <a href={filesApi.downloadUrl(f.id)} download class="p-1.5 rounded-lg hover:bg-gray-800 text-gray-500 hover:text-sky-400" title="下载">
                  <Download class="w-4 h-4" />
                </a>
                <button onclick={() => handleDelete(f.id, f.original_name)} class="p-1.5 rounded-lg hover:bg-gray-800 text-gray-500 hover:text-red-400" title="删除">
                  <Trash2 class="w-4 h-4" />
                </button>
              </div>
            </div>
            <p class="text-sm font-medium text-gray-200 truncate mb-1" title={f.original_name}>{f.original_name}</p>
            <div class="flex items-center gap-2 text-xs text-gray-500 mb-2">
              {#if f.folder}
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-violet-500/10 text-violet-400 border border-violet-500/20">
                  <FolderOpen class="w-3 h-3" />
                  {f.folder}
                </span>
                <span>·</span>
              {/if}
              <span>{f.size_human}</span>
              <span>·</span>
              <span>{formatDateTime(f.created_at)}</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border {badge.class}">
                <badge.icon class="w-3 h-3" />
                {badge.label}
              </span>
              {#if f.tags && f.tags.length > 0}
                {#each f.tags.slice(0, 2) as tag}
                  <span class="px-2 py-0.5 rounded-full text-xs bg-gray-800 text-gray-500">{tag}</span>
                {/each}
              {/if}
            </div>
          </div>
        {/each}
      </div>

      <!-- Pagination -->
      {#if totalPages > 1}
        <div class="flex items-center justify-center gap-2 mt-6">
          <button
            disabled={page <= 1}
            onclick={() => { page--; loadFiles(); }}
            class="px-3 py-1.5 rounded-lg text-xs bg-gray-800 text-gray-400 hover:bg-gray-700 disabled:opacity-40"
          >
            上一页
          </button>
          <span class="text-xs text-gray-600">{page} / {totalPages}</span>
          <button
            disabled={page >= totalPages}
            onclick={() => { page++; loadFiles(); }}
            class="px-3 py-1.5 rounded-lg text-xs bg-gray-800 text-gray-400 hover:bg-gray-700 disabled:opacity-40"
          >
            下一页
          </button>
        </div>
      {/if}
    {/if}
  </div>
</div>
