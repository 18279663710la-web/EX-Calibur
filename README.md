# Excalibur / CloudRAG-Hub

Excalibur 是一个基于 Dify Chatflow 的个人文件检索助手。Web 端提供文件上传、打开文件、RAG 问答和通道管理；移动端通过微信通道交互。CloudRAG 后端只作为网关层：接收 Web 或微信消息，转发到 Dify 或本地文件库，再把结果回传给对应通道。RAG 检索、知识库问答、文件清洗与索引质量由 Dify 工作流和同步脚本负责。

<img width="2527" height="1330" alt="CloudRAG Web" src="https://github.com/user-attachments/assets/78036e7c-cc7b-4253-887e-69e3465d6231" />

## 功能概览

- CloudRAG-Hub Web 页面：文本问答、文件上传、文件打开/预览、通道管理。
- 微信通道：接入 ClawBot/iLink 后主动轮询微信消息。
- 文本消息：转发到 Dify Chatflow，并把答案发回原用户。
- 文件消息：写入 `knowledge/` 文件库，并发送上传确认。
- 打开/查看文件：Web 端返回可预览信息；微信端直接通过 send-file 回传文件本体。
- 文件库同步：定时扫描 `knowledge/`，清洗成 Markdown，并上传到 Dify Dataset。

## 项目结构

```text
.
├── backend/                       # FastAPI 网关服务
├── frontend/                      # Svelte + Vite 前端，Docker 中由 Nginx 托管
├── knowledge/                     # 本地文件库，Web/微信上传文件会落到这里
├── structured_markdown_retrieval/ # 可选的检索优化 Markdown 示例语料
├── EX咖喱棒.yml                   # Dify Chatflow DSL
├── agent_server.py                # 可选的本地文件库 HTTP 服务
├── sync_script.py                 # 文件库到 Dify Dataset 的同步脚本
├── knowledge-sync.Dockerfile      # 同步脚本容器镜像
├── docker-compose.yml             # 一键启动配置
└── .env.example                   # 环境变量模板
```

Dify Chatflow：

<img width="2112" height="1224" alt="Dify Chatflow" src="https://github.com/user-attachments/assets/1bdff0ad-d202-41f1-8761-54f052ed31a9" />

`tests/`、`reports/`、`.pytest_cache/`、`.env`、运行时上传目录和同步账本不提交到 GitHub。

## 运行前准备

需要先准备：

- Docker 与 Docker Compose。
- 一个可用的 Dify 实例，可以是本地 Dify Docker，也可以是 Dify Cloud。
- 已导入并发布的 Dify Chatflow。
- 如需微信通道，准备可用的 ClawBot/iLink 登录态和 Token。

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

Linux/macOS：

```bash
cp .env.example .env
```

至少修改这些变量：

```env
JWT_SECRET_KEY=change-me-to-a-random-64-character-secret
POSTGRES_PASSWORD=change-me
DIFY_BASE_URL=http://api:5001/v1
DIFY_API_KEY=your-dify-app-api-key
```

如果 Dify 是本机 Docker 部署，并且 CloudRAG 加入了 Dify 的 `docker_default` 网络，推荐：

```env
DIFY_BASE_URL=http://api:5001/v1
```

如果 CloudRAG 容器需要访问宿主机上的 Dify：

```env
DIFY_BASE_URL=http://host.docker.internal/v1
```

如果使用 Dify Cloud：

```env
DIFY_BASE_URL=https://api.dify.ai/v1
```

不要提交 `.env`，里面会包含真实密钥。

## 导入 Dify 工作流

1. 打开 Dify 控制台。
2. 选择目标 Workspace。
3. 导入仓库根目录的 `EX咖喱棒.yml`。
4. 安装工作流缺少的模型插件，并配置模型供应商凭据。
5. 创建或选择 Dataset 知识库。
6. 将工作流里的知识库检索节点绑定到你的 Dataset。
7. 发布应用。
8. 复制 App API Key，填入 `.env` 的 `DIFY_API_KEY`。

CloudRAG 后端会把用户输入转发给 Dify Chatflow 的用户输入节点，核心请求结构如下：

```json
{
  "inputs": {
    "userinput": {
      "query": "用户问题",
      "files": []
    }
  },
  "query": "用户问题",
  "response_mode": "streaming",
  "user": "channel-user-id"
}
```

## 一键启动

在项目根目录执行：

```powershell
docker compose up -d --build
```

启动后默认访问：

- Web 页面：http://localhost:8081
- 后端健康检查：http://localhost:8080/health
- 微信通道状态：http://localhost:8080/api/v1/clawbot/weixin-state

默认初始化账号：

```text
admin / Admin@123456
demo_user / Demo@123456
```

公开部署前请修改默认账号、数据库密码和 JWT 密钥。

查看日志：

```powershell
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f knowledge-sync
```

## 微信通道

微信通道沿用 Web 端的大部分交互逻辑，区别是“打开/查看文件”必须回传文件本体。

当前链路：

1. 后端连接 ClawBot/iLink。
2. 后端主动轮询微信消息。
3. 文本消息转发到 Dify，再通过微信文本消息回给用户。
4. 文件消息下载后写入 `knowledge/`，再回确认消息。
5. “打开/查看 文件名”会从 `knowledge/` 查找文件，并调用微信 send-file。

连接后可以检查：

```powershell
Invoke-RestMethod http://localhost:8080/api/v1/clawbot/weixin-state
```

返回中的 `connected`、`running`、`polling` 为 `true` 时，说明通道轮询已经启动。

## 文件库同步

`knowledge-sync` 容器默认每 60 秒扫描一次 `knowledge/`。配置这些变量后，它会把文件清洗成 Markdown 并上传到 Dify Dataset：

```env
DIFY_DATASET_API_KEY=your-dataset-api-key
DIFY_DATASET_ID=your-dataset-id
CLOUDRAG_DEEPSEEK_API_KEY=your-cleaning-model-key
SYNC_INTERVAL_SECONDS=60
SYNC_RUN_ON_START=true
```

如果这些变量为空，同步容器会保持运行但跳过上传，不影响 Web 和微信网关启动。

也可以本地手动运行同步脚本：

```powershell
pip install -r knowledge-sync-requirements.txt
python sync_script.py --source-dir knowledge
```

## 本地开发

后端：

```powershell
cd backend
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

可选文件库服务：

```powershell
pip install fastapi uvicorn python-multipart
python agent_server.py
```

## 发布检查

提交前建议检查：

```powershell
docker compose config --quiet
python -m py_compile backend\src\services\channels.py backend\src\routes\channels.py backend\src\routes\clawbot.py backend\src\services\dify.py sync_script.py agent_server.py
git status --short
```

确认不要提交：

- `.env`
- Dify、模型供应商、微信或 JWT 的真实密钥
- `tests/`
- `reports/`
- `.pytest_cache/`
- `sync_ledger*.json`
- `dify_backups/`
- `backend/uploads/`
- `frontend/node_modules/`

## 说明

- `api-contract.md` 不作为当前项目真实接口依据。
- 后端只负责鉴权、通道适配、请求转发、文件落库、流式透传和微信回传。
- RAG、Embedding、Chunk、重排、清洗与 Dataset 索引由 Dify 工作流和同步脚本负责。
