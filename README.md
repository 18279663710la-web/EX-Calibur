# Excalibur

Excalibur是一个个人文件检索助手，以Dify Chatflow为底座，在web页面中能进行文件上传、打开、以及RAG检索文件内容操作，移动端以微信作为交互通道。
<img width="2527" height="1330" alt="image" src="https://github.com/user-attachments/assets/78036e7c-cc7b-4253-887e-69e3465d6231" />

## 主要功能

- 通过 Dify App API 转发文本对话和文件对话。
- 支持流式响应、会话记录、Token 与延迟统计。
- 支持微信 / Clawbot 通道管理。
- 支持本地文件库服务 `agent_server.py`，用于文件搜索、上传和本地文件入口。
- 支持将本地 Markdown、Word、PDF 等文档同步到 Dify 知识库。
- 使用 PostgreSQL 保存 CloudRAG 本地账号、文件、会话、消息和审计日志。

## 项目结构

```text
.
├── backend/                         # FastAPI 后端网关
├── frontend/                        # Svelte + Vite 前端，Docker 中由 Nginx 托管
├── tests/                           # 后端、Dify 调用和同步脚本测试
├── knowledge/                       # 本地文件库示例目录，会挂载给 agent-server
├── structured_markdown_retrieval/   # 适合导入 Dify 知识库的检索增强 Markdown
├── EX咖喱棒.yml                     # 从 Dify 导出的 Chatflow DSL
├── agent_server.py                  # 本地文件库 Agent 服务
├── sync_script.py                   # 本地文档同步到 Dify 知识库的可选脚本
├── docker-compose.yml               # 一键启动配置
└── .env.example                     # 环境变量模板，不包含真实密钥
```
Dify Chatflow：

<img width="2112" height="1224" alt="EX咖喱棒 (1)" src="https://github.com/user-attachments/assets/1bdff0ad-d202-41f1-8761-54f052ed31a9" />


## 环境要求

- Docker 和 Docker Compose。
- 一个可用的 Dify 实例，可以是本地 Docker 部署，也可以是 Dify Cloud。
- 如果本地开发前端，需要 Node.js 22+。
- 如果本地开发后端或运行同步脚本，需要 Python 3.12+。

## 环境变量

复制模板：

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

至少需要配置：

- `JWT_SECRET_KEY`：CloudRAG 本地登录用 JWT 密钥。
- `POSTGRES_PASSWORD`：CloudRAG 本地 PostgreSQL 密码。
- `DIFY_BASE_URL`：Dify API 地址。
- `DIFY_API_KEY`：Dify 应用发布后的 App API Key。
- `FRONTEND_PORT`：前端访问端口，默认 `8081`。
- `AGENT_PORT`：文件库 Agent 服务端口，默认 `8090`。

如果 Dify 是本机 Docker 部署，并且通过 `http://localhost` 暴露，推荐：

```env
DIFY_BASE_URL=http://host.docker.internal/v1
```

如果使用 Dify Cloud：

```env
DIFY_BASE_URL=https://api.dify.ai/v1
```

不要提交 `.env` 文件。该文件已经被 `.gitignore` 忽略。

## 在 Dify 中导入当前工作流

1. 打开 Dify 控制台。
2. 进入目标 Workspace。
3. 选择“导入 DSL / 导入应用”。
4. 选择仓库根目录下的 `EX咖喱棒.yml`。
5. 如果 Dify 提示缺少模型插件，请安装工作流依赖的模型插件。
6. 配置对应模型供应商凭据。
7. 创建或选择知识库。
8. 打开导入后的工作流，将知识检索节点绑定到自己的知识库。
9. 发布应用。
10. 复制 Dify 生成的 App API Key，填入 `.env` 的 `DIFY_API_KEY`。

CloudRAG 后端会按下面结构调用 Dify Chat Messages API：

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
  "user": "username"
}
```

## 导入示例知识库文档

推荐将 `structured_markdown_retrieval/` 中的 Markdown 文件导入 Dify 知识库。这些文件已经增加来源、章节标题和检索关键词提示，更适合混合检索。

推荐的 Dify 知识库设置：

- 索引模式：高质量。
- 分段模式：自定义。
- 分段符：`\n## `。
- 最大分段 Token：约 `800`。
- 检索方式：混合检索。
- Top K：`20`。
- Score threshold：关闭或设为 `0`。
- Rerank：如果模型供应商已配置，建议开启。

也可以使用同步脚本上传：

```bash
pip install -r backend/requirements.txt

export DIFY_BASE_URL=http://localhost/v1
export DIFY_DATASET_API_KEY=your-dataset-api-key
export DIFY_DATASET_ID=your-dataset-id
export LOCAL_FILE_DIR=structured_markdown_retrieval

python sync_script.py --source-dir structured_markdown_retrieval
```

Windows PowerShell：

```powershell
$env:DIFY_BASE_URL="http://localhost/v1"
$env:DIFY_DATASET_API_KEY="your-dataset-api-key"
$env:DIFY_DATASET_ID="your-dataset-id"
$env:LOCAL_FILE_DIR="structured_markdown_retrieval"

python sync_script.py --source-dir structured_markdown_retrieval
```

## 使用 Docker Compose 启动

确认 `.env` 已配置后，在项目根目录执行：

```bash
docker compose up -d --build
```

Compose 会同时启动 4 个服务：

- `frontend`：前端页面，默认访问 `http://localhost:8081`。
- `backend`：CloudRAG FastAPI 网关，容器内端口 `8080`。
- `agent-server`：本地文件库 Agent 服务，默认访问 `http://localhost:8090/health`。
- `postgres`：CloudRAG 本地数据库。

查看日志：

```bash
docker compose logs -f backend
docker compose logs -f agent-server
docker compose logs -f frontend
```

默认初始化账号在 `backend/init.sql` 中：

```text
admin / Admin@123456
demo_user / Demo@123456
```


## 本地开发

后端网关：

```bash
cd backend
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
```

文件库 Agent 服务：

```bash
pip install -r agent-server-requirements.txt
python agent_server.py
```

如需修改文件库目录：

```bash
export AGENT_KNOWLEDGE_DIR=knowledge
export AGENT_PORT=8090
python agent_server.py
```

Windows PowerShell：

```powershell
$env:AGENT_KNOWLEDGE_DIR="knowledge"
$env:AGENT_PORT="8090"
python agent_server.py
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## 测试

后端和同步脚本测试：

```bash
pip install -r backend/requirements.txt
pip install -r agent-server-requirements.txt
python -m pytest
```

前端测试与构建：

```bash
cd frontend
npm install
npx vitest run
npm run build
```

Compose 配置检查：

```bash
docker compose config --quiet
```
