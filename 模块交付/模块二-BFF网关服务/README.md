# 模块二：BFF 网关服务

## 职责

后端 FastAPI 应用的核心层：应用入口、配置管理、数据库连接池、JWT 认证中间件、审计日志中间件、通用响应模型、认证/文件/管线占位路由、文件匹配与上传校验服务。

## 交付清单

### 代码文件

| 文件 | 说明 |
|------|------|
| `backend/src/main.py` | FastAPI 应用工厂（lifespan、CORS、路由注册、WebSocket、/health 端点） |
| `backend/src/config.py` | Pydantic Settings 配置类（JWT、DB、Dify、微信、上传参数） |
| `backend/src/database.py` | asyncpg 连接池管理（get_pool、close_pool） |
| `backend/src/middleware/__init__.py` | 包标记 |
| `backend/src/middleware/auth.py` | JWT 签发/验证 + `get_current_user()` 依赖注入 |
| `backend/src/middleware/logging.py` | 审计日志中间件：request_id + latency_ms + 写入 operation_logs |
| `backend/src/models/__init__.py` | 通用模型：Envelope（统一响应）、PaginatedData、UserBrief、FileInfo、ConversationBrief、MessageItem |
| `backend/src/routes/__init__.py` | 路由聚合：汇总 7 个路由模块 |
| `backend/src/routes/auth.py` | 认证路由：POST /login、/register、/refresh、GET /me |
| `backend/src/routes/files.py` | 文件路由：GET /files（分页列表）、DELETE /files/{id}（软删除+配额归还） |
| `backend/src/routes/pipeline.py` | 管线状态路由：GET /status/{task_id}（占位） |
| `backend/src/services/__init__.py` | 包标记 |
| `backend/src/services/file_matcher.py` | 文件名模糊匹配（rapidfuzz）：中文查询解析、混合评分、三级匹配策略 |
| `backend/src/services/dynamic_rag.py` | 对话文件上传校验常量（白名单扩展名、大小限制、数量限制） |
| `backend/src/services/pipeline_store.py` | 内存级管线任务存储（WebSocket 轮询用） |
| `backend/src/services/dify_sync.py` | Dify 文档同步占位（预留接口） |
| `backend/requirements.txt` | 后端 Python 依赖（fastapi、uvicorn、python-jose、passlib、bcrypt、asyncpg、httpx、pydantic、chardet、python-docx、PyPDF2、rapidfuzz 等 18 个包） |

### API 文档

| 文档 | 说明 |
|------|------|
| **通用响应规范** | Envelope 格式：`{code, message, data, meta{request_id, timestamp, latency_ms}}` |
| **错误码定义** | 40001(参数错误)、40101(未认证)、40102(Token过期)、40301(权限不足)、40401(资源不存在)、40901(冲突)、41301(文件过大)、42201(类型不支持)、50001(服务器错误) 等共 15 个错误码 |
| **分页规范** | 请求参数 page(默认1)+page_size(默认20最大100)；响应格式 items+total+page+page_size+total_pages |
| **auth 接口文档** | POST /api/v1/auth/login（请求体 username+password → 返回 access_token+refresh_token+user）；POST /register（username+email+password+confirm_password → 注册校验规则）；POST /refresh；GET /me（返回配额信息） |

## 上游依赖

| 上游模块 | 依赖方式 |
|----------|----------|
| 模块一（部署） | docker-compose 提供 PostgreSQL 连接、JWT_SECRET_KEY、Dify 配置等环境变量 |
| 模块七（数据库） | 数据库表（users、file_metadata）需要 init.sql 提前创建 |

## 下游对接

| 下游模块 | 对接方式 |
|----------|----------|
| 模块三（前端） | Nginx 将 /api/* 代理到 backend:8080，前端 api.ts 调用本模块的所有路由 |
| 模块四（AI引擎） | routes/chat.py 调用本模块的 `get_current_user()` 认证依赖；models/__init__.py 的 Envelope 被 chat 路由复用 |
| 模块五（文件管线） | file_matcher.py 被 agent_server 和微信通道复用进行文件搜索 |
| 模块六（微信通道） | file_matcher.py 被 weixin handler 调用做知识库文件匹配 |
| 模块七（看板） | middleware/logging.py 写入的 operation_logs 被 dashboard 路由查询 |

## 交付标准

- [ ] POST /api/v1/auth/login 使用正确凭证返回 JWT token
- [ ] POST /api/v1/auth/register 校验密码强度、用户名/邮箱唯一性
- [ ] GET /api/v1/files 返回当前用户的分页文件列表
- [ ] DELETE /api/v1/files/{id} 软删除文件并归还配额
- [ ] 未携带 Token 访问受保护接口返回 401
- [ ] 审计日志中间件为每个请求生成 request_id 并写入 operation_logs
- [ ] file_matcher 能正确处理中文查询（如"打开架构文档" → 匹配"架构文档.docx"）
- [ ] 所有 API 响应符合 Envelope 格式
- [ ] requirements.txt 中所有依赖可正常安装
