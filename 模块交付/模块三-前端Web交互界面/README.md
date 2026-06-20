# 模块三：前端 Web 交互界面

## 职责

基于 Svelte 5 的单页应用（SPA）：Hash 路由、对话界面（SSE 打字机效果）、文件管理（上传/浏览/删除）、管理看板（Chart.js 图表）、通道管理、登录/注册、Nginx 反向代理。

## 交付清单

### 代码文件

| 文件 | 说明 |
|------|------|
| `frontend/src/main.ts` | 应用入口，挂载 App 组件到 #app |
| `frontend/src/App.svelte` | 根组件：Hash 路由（#/chat、#/dashboard、#/channels、#/login、#/register），登录态守卫 |
| `frontend/src/lib/api.ts` | API 客户端（560行）：全部 TypeScript 类型定义 + request<T>() 统一封装 + 自动 Token 刷新 + 5 个业务 API 分组（authApi/filesApi/dashboardApi/kbApi/channelsApi） |
| `frontend/src/lib/sse.ts` | SSE 流式客户端（320行）：parseSSEBlock() 解析器 + createChatStream() 流式接收 + 6 种事件处理 + mock 模式 |
| `frontend/src/lib/stores.ts` | 全局状态管理：currentUser/isLoggedIn/sidebarOpen/toasts + 工具函数（日期格式化、字节/Token 可读转换） |
| `frontend/src/components/AppLayout.svelte` | 主布局：侧边栏 + 顶栏（通道管理/数据看板按钮） + 内容区 |
| `frontend/src/components/ChatView.svelte` | 对话界面（501行）：历史消息渲染 + SSE 流式打字机效果 + 文件上传 + Markdown 解析 + 引用展示 |
| `frontend/src/components/FileManager.svelte` | 文件管理（382行）：分页网格 + 搜索过滤 + 拖拽上传 + 分段设置面板 + Dify 自动同步（5秒轮询） |
| `frontend/src/components/Sidebar.svelte` | 侧边栏（187行）：对话历史列表（50条）+ 右键删除 + 用户信息 + 登出 |
| `frontend/src/components/Login.svelte` | 登录/注册（168行）：表单验证 + JWT 存储 + 密码强度校验 |
| `frontend/src/components/Dashboard.svelte` | 数据看板（261行）：Chart.js 趋势图 + 统计卡片 + 用户排行表 |
| `frontend/src/components/ChannelManager.svelte` | 通道管理（277行）：通道状态展示 + 连接/断开 + 微信扫码登录 |
| `frontend/src/components/MobileNav.svelte` | 移动端底部导航（34行） |
| `frontend/src/components/Toast.svelte` | 全局通知组件（27行）：success/error/info 三种类型，4s 自动消失 |
| `frontend/src/styles/global.css` | 全局样式：光标闪烁动画、Token 淡入、滚动条样式、安全区域 |
| `frontend/nginx.conf` | Nginx 配置（111行）：SPA 回退 + /api/ 代理到 backend:8080 + SSE 长连接 + 安全头 + Gzip |
| `frontend/Dockerfile` | 多阶段构建：Node 22 构建 → Nginx 1.27 托管 |
| `frontend/package.json` | 依赖声明：svelte、vite、tailwindcss、chart.js、lucide-svelte |

### API 文档

| 文档 | 说明 |
|------|------|
| **SSE 流式协议对接说明** | 6 种事件格式（meta/references/message/tool_call/error/done）的解析方式和前端处理逻辑 |
| **API 请求头规范** | `Authorization: Bearer <token>`、`Content-Type: application/json`、文件上传使用 `multipart/form-data` |
| **Token 刷新机制** | 前端 401 自动刷新流程：原请求失败 → 调用 /auth/refresh → 成功则重试 → 失败则跳转登录页 |
| **文件上传约束** | 对话附件：单批最多 5 个、单文件 ≤15MB、白名单 13 种扩展名、每天最多 20 次；文件管理：单批最多 5 个、单文件 ≤15MB |

## 上游依赖

| 上游模块 | 依赖方式 |
|----------|----------|
| 模块一（部署） | Dockerfile 构建，Nginx 代理到 backend:8080 |
| 模块二（BFF网关） | 所有 /api/v1/* 请求通过 Nginx 代理到 backend:8080 |
| 模块四（AI引擎） | SSE 流式对话对接 chat_stream() 生成器输出的 6 种事件 |

## 下游对接

无（前端是用户交互终点，不向其他模块提供接口）。

## 交付标准

- [ ] 登录/注册功能正常，JWT 正确存储和刷新
- [ ] 新建对话 → 输入问题 → SSE 逐 Token 打字机效果流畅
- [ ] 对话附件上传：拖拽/点击 → 上传进度条 → 文件标签显示"同步中"/"已归档"
- [ ] 历史对话列表加载正常，右键删除工作
- [ ] 文件管理：分页加载、搜索过滤、批量上传、删除确认、Dify 同步
- [ ] 管理员看板：Chart.js 图表渲染、日期筛选、用户排行
- [ ] 通道管理：微信通道连接/断开、二维码获取与轮询
- [ ] 移动端适配：底部导航显示/隐藏
- [ ] Nginx 反向代理：SSE 长连接不断开、大文件上传不超时
- [ ] `npm run build` 无警告无错误
