<script lang="ts">
  import { setUser, toastSuccess } from '../lib/stores';
  import { authApi, saveAuth } from '../lib/api';
  import { Cloud } from 'lucide-svelte';

  interface Props {
    isRegister: boolean;
  }

  let { isRegister }: Props = $props();

  let username = $state('');
  let email = $state('');
  let password = $state('');
  let confirmPassword = $state('');
  let loading = $state(false);
  let errorMsg = $state('');
  let isRegisterMode = $state(false);

  $effect(() => { isRegisterMode = isRegister; });

  async function handleSubmit(e: Event) {
    e.preventDefault();
    errorMsg = '';
    loading = true;

    try {
      if (isRegisterMode) {
        if (password !== confirmPassword) {
          errorMsg = '两次密码输入不一致';
          loading = false;
          return;
        }
        const res = await authApi.register({ username, email, password, confirm_password: confirmPassword });
        if (res.code === 201) {
          toastSuccess('注册成功，请登录');
          isRegisterMode = false;
          window.location.hash = '#/login';
        }
      } else {
        const res = await authApi.login({ username, password });
        if (res.code === 200 && res.data) {
          saveAuth(res.data);
          setUser(res.data.user);
          toastSuccess('登录成功');
          window.location.hash = '#/chat';
        }
      }
    } catch (err: unknown) {
      const e = err as { message?: string };
      errorMsg = e?.message || '请求失败，请检查网络';
    } finally {
      loading = false;
    }
  }

  function toggleMode() {
    isRegisterMode = !isRegisterMode;
    window.location.hash = isRegisterMode ? '#/register' : '#/login';
    errorMsg = '';
  }
</script>

<div
  class="monochrome-shell flex min-h-dvh items-center justify-center bg-white px-4 py-12 text-black font-[Georgia,serif]"
  style="background-image: repeating-linear-gradient(0deg, transparent, transparent 1px, rgba(0,0,0,0.018) 1px, rgba(0,0,0,0.018) 2px); background-size: 100% 4px;"
>
  <div class="w-full max-w-lg">
    <div class="mb-10 border-b-4 border-black pb-8 text-center">
      <div class="mb-6 inline-flex h-16 w-16 items-center justify-center border-4 border-black bg-black">
        <Cloud class="h-8 w-8 text-white" />
      </div>
      <h1 class="text-5xl font-semibold leading-none tracking-tight text-black md:text-6xl">CloudRAG</h1>
      <p class="mt-4 font-mono text-xs uppercase tracking-widest text-gray-600">
        {isRegisterMode ? '创建账号开始使用' : '登录知识库管理平台'}
      </p>
    </div>

    <form onsubmit={handleSubmit} class="space-y-6 border-4 border-black bg-white p-6 md:p-8">
      {#if errorMsg}
        <div class="border-2 border-black bg-black px-3 py-2 text-sm text-white">
          {errorMsg}
        </div>
      {/if}

      <div>
        <label for="username" class="mb-2 block font-mono text-xs uppercase tracking-widest text-gray-600">用户名</label>
        <input
          id="username"
          type="text"
          bind:value={username}
          required
          minlength={3}
          maxlength={32}
          pattern="[a-zA-Z0-9_]+"
          class="w-full border-0 border-b-2 border-black bg-white px-0 py-3 text-base text-black placeholder:text-gray-600 focus:border-b-4 focus:outline-none"
          placeholder="请输入用户名"
        />
      </div>

      {#if isRegisterMode}
        <div>
          <label for="email" class="mb-2 block font-mono text-xs uppercase tracking-widest text-gray-600">邮箱 (.edu.cn)</label>
          <input
            id="email"
            type="email"
            bind:value={email}
            required
            class="w-full border-0 border-b-2 border-black bg-white px-0 py-3 text-base text-black placeholder:text-gray-600 focus:border-b-4 focus:outline-none"
            placeholder="zhangsan@cs.university.edu.cn"
          />
        </div>
      {/if}

      <div>
        <label for="password" class="mb-2 block font-mono text-xs uppercase tracking-widest text-gray-600">密码</label>
        <input
          id="password"
          type="password"
          bind:value={password}
          required
          minlength={8}
          maxlength={64}
          class="w-full border-0 border-b-2 border-black bg-white px-0 py-3 text-base text-black placeholder:text-gray-600 focus:border-b-4 focus:outline-none"
          placeholder="8位以上，包含大小写、数字与特殊字符"
        />
      </div>

      {#if isRegisterMode}
        <div>
          <label for="confirmPassword" class="mb-2 block font-mono text-xs uppercase tracking-widest text-gray-600">确认密码</label>
          <input
            id="confirmPassword"
            type="password"
            bind:value={confirmPassword}
            required
            class="w-full border-0 border-b-2 border-black bg-white px-0 py-3 text-base text-black placeholder:text-gray-600 focus:border-b-4 focus:outline-none"
            placeholder="再次输入密码"
          />
        </div>
      {/if}

      <button
        type="submit"
        disabled={loading}
        class="min-h-12 w-full border-2 border-black bg-black py-3 font-mono text-xs font-medium uppercase tracking-widest text-white transition-colors duration-100 hover:bg-white hover:text-black disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        {#if loading}
          <span class="mr-2 inline-block h-4 w-4 animate-spin border-2 border-white/30 border-t-white align-middle"></span>
        {/if}
        {isRegisterMode ? '注册' : '登录'}
      </button>

      <div class="text-center text-sm text-gray-600">
        {isRegisterMode ? '已有账号？' : '没有账号？'}
        <button type="button" onclick={toggleMode} class="ml-1 border-b border-black text-black hover:bg-black hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2">
          {isRegisterMode ? '去登录' : '去注册'}
        </button>
      </div>
    </form>

    {#if !isRegisterMode}
      <p class="mt-5 text-center font-mono text-xs uppercase tracking-widest text-gray-600">
        演示账号: admin / Admin@123456 或 demo_user / Demo@123456
      </p>
    {/if}
  </div>
</div>
