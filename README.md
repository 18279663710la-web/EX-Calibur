# CloudRAG-Hub

CloudRAG-Hub 是一个面向 Dify Chatflow 的本地 RAG 网关与 Web 控制台。项目后端不承担复杂的数据处理逻辑，只负责接收用户消息或文件、转发给 Dify、将 Dify 的结果流式返回给前端，并提供账号、通道、文件和数据看板等本地管理接口。前端使用 Svelte 构建，整体是黑白线框风格的知识库对话与管理界面。

## 主要功能

- 通过 Dify App API 转发文本对话和文件对话。
- 支持知识库对话、流式响应、检索引用展示。
- 支持微信 / Clawbot 通道管理。
- 支持本地用户登录、文件元数据管理和管理端数据看板。
- 使用 PostgreSQL 保存 CloudRAG 本地账号、文件、会话、消息和审计日志。
- 提供可选的知识库同步脚本，用于将本地 Markdown、Word、PDF 等文档上传到 Dify 知识库。

## 项目结构

```text
.
├── backend/                         # FastAPI 后端网关
├── frontend/                        # Svelte + Vite 前端，Docker 中由 Nginx 托管
├── tests/                           # 后端与同步脚本测试
├── knowledge/                       # 可选的本地示例原始文档
├── structured_markdown_retrieval/   # 适合导入 Dify 知识库的检索增强版 Markdown
├── EX咖喱棒.yml                      # 从 Dify 导出的 Chatflow DSL
├── sync_script.py                   # 本地文档同步到 Dify 知识库的可选脚本
├── docker-compose.yml               # CloudRAG 一键启动配置
└── .env.example                     # 环境变量模板，不包含真实密钥
```

`其他/` 文件夹是本地参考资料，已经在 `.gitignore` 中忽略，不会上传到 GitHub。

## 环境要求

- Docker 和 Docker Compose。
- 一个可用的 Dify 实例，可以是 Dify Cloud，也可以是本地 Docker 部署。
- 如果不使用 Docker 运行前端，需要 Node.js 22+。
- 如果不使用 Docker 运行后端或测试脚本，需要 Python 3.12+。

## 环境变量配置

复制模板文件：

```bash
cp .env.example .env
```

Windows PowerShell 可以使用：

```powershell
Copy-Item .env.example .env
```

至少需要配置以下字段：

- `JWT_SECRET_KEY`：JWT 密钥，建议使用 `openssl rand -hex 32` 生成。
- `POSTGRES_PASSWORD`：CloudRAG 本地 PostgreSQL 密码。
- `DIFY_BASE_URL`：Dify API 地址。
- `DIFY_API_KEY`：导入并发布 Dify 工作流后生成的 App API Key。

如果 Dify 是本机 Docker 部署，并且 Dify nginx 暴露在 `http://localhost`，推荐：

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
3. 选择导入 DSL / 导入应用。
4. 选择仓库根目录下的 `EX咖喱棒.yml`。
5. 如果 Dify 提示缺少插件，请安装工作流依赖的模型插件，例如：
   - DeepSeek
   - Tongyi
6. 在 Dify 中配置对应模型供应商的凭据。
7. 创建或选择一个知识库。
8. 打开导入后的工作流，将知识检索节点绑定到你自己的知识库。
9. 发布应用。
10. 复制 Dify 生成的 App API Key，填入 `.env` 的 `DIFY_API_KEY`。

CloudRAG 后端会按以下结构调用 Dify Chat Messages API：

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

推荐将 `structured_markdown_retrieval/` 中的 Markdown 文件导入 Dify 知识库。该目录中的文档已经加入了来源文件、章节标题和检索关键词提示，更适合混合检索，提高召回率。

推荐的 Dify 知识库设置：

- 索引模式：高质量。
- 分段模式：自定义。
- 分段符：`\n## `。
- 最大分段 Token：约 `800`。
- 检索方式：混合检索。
- Top K：`20`。
- Score threshold：关闭或设为 `0`。
- Rerank：如果模型供应商已配置，建议开启。
- 关键词 / 向量权重：可先使用 `0.5 / 0.5`。

也可以使用同步脚本上传：

```bash
pip install -r backend/requirements.txt

export DIFY_BASE_URL=http://localhost/v1
export DIFY_DATASET_API_KEY=your-dataset-api-key
export DIFY_DATASET_ID=your-dataset-id
export LOCAL_FILE_DIR=structured_markdown_retrieval

python sync_script.py --source-dir structured_markdown_retrieval
```

Windows PowerShell 示例：

```powershell
$env:DIFY_BASE_URL="http://localhost/v1"
$env:DIFY_DATASET_API_KEY="your-dataset-api-key"
$env:DIFY_DATASET_ID="your-dataset-id"
$env:LOCAL_FILE_DIR="structured_markdown_retrieval"

python sync_script.py --source-dir structured_markdown_retrieval
```

## 使用 Docker Compose 启动

确认 `.env` 已配置完成后，在项目根目录执行：

```bash
docker compose up -d --build
```

访问：

```text
http://localhost:8081
```

默认初始化账号在 `backend/init.sql` 中：

```text
admin / Admin@123456
demo_user / Demo@123456
```

如果要公开部署，请务必修改默认账号、数据库密码和 JWT 密钥。

## 本地开发

后端：

```bash
cd backend
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

如果后端不在 Docker 中运行，可以将 Dify 地址设为宿主机可访问地址：

```env
DIFY_BASE_URL=http://localhost/v1
```

## 测试

后端和同步脚本测试：

```bash
pip install -r backend/requirements.txt
python -m pytest
```

前端测试与构建：

```bash
cd frontend
npm install
npx vitest run
npm run build
```

## 发布到 GitHub 前检查

上传仓库前请确认：

- `.env` 没有被加入 Git。
- 没有提交真实的 Dify App Key、Dataset Key、模型供应商 Key、JWT Secret 或微信 Token。
- `sync_ledger*.json`、`dify_backups/`、`uploads/`、`node_modules/`、`其他/` 等本地运行产物和参考资料没有被加入 Git。
- 如需公开部署，替换默认数据库密码和默认种子用户密码。

可以使用下面的命令检查：

```bash
git status --short
git diff --cached
```

## 说明

- 数据看板读取的是 CloudRAG 本地 PostgreSQL 表，不是 Dify 官方统计面板。
- 本项目后端定位为网关层：RAG 检索、知识库处理和复杂业务流程应放在 Dify 工作流与 Dify 知识库中完成。
