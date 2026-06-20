# 模块七：数据看板与分析引擎

## 职责

PostgreSQL 数据库 Schema 设计与初始化、管理员数据分析看板 API、审计日志追踪、统计预聚合视图、数据库连接池管理。为管理员提供平台运营数据的可视化分析能力。

## 交付清单

### 代码文件

| 文件 | 说明 |
|------|------|
| `backend/init.sql` | 数据库 Schema 初始化（246行）：7 张表（users/file_metadata/file_vectors/mobile_session_context/conversations/messages/operation_logs）+ 2 个视图（v_user_stats/v_daily_stats）+ 种子数据 + 25+ 个索引 + updated_at 触发器 |
| `backend/src/routes/dashboard.py` | 管理看板路由（349行）：GET /overview、GET /stats（综合统计）、GET /stats/timeline（时间序列）、GET /stats/users（用户排名）。所有端点仅管理员可访问 |
| `backend/src/database.py` | asyncpg 连接池管理：get_pool()、close_pool() |
| `backend/src/middleware/logging.py` | 审计日志中间件：AuditLoggingMiddleware（request_id + latency_ms 记录）+ log_request_to_db()（写入 operation_logs） |

### 数据库表清单

| 表名 | 说明 | 行数占比 |
|------|------|----------|
| `users` | 用户表：UUID 主键、bcrypt 密码、角色(user/admin)、存储配额(默认 1GB) | 核心 |
| `file_metadata` | 文件元数据：original_name/mime_type/size/tags/folder/processing_status/duplicate_of/dify_document_id/deleted_at(软删除) | 核心 |
| `file_vectors` | 文件级向量存储：embedding(JSONB 2560维)、model(qwen3-embedding:4b) | 辅助 |
| `mobile_session_context` | 移动端会话上下文：external_user_id/mode/target_file_id | 辅助 |
| `conversations` | 对话表：title/model/user_id(FK)/created_at/updated_at | 核心 |
| `messages` | 消息表：conversation_id(FK)/role/prompt_tokens/completion_tokens/total_tokens/latency_ms/references_json/tool_calls_json | 核心 |
| `operation_logs` | 操作日志：user_id/request_id/method/path/status_code/latency_ms/ip_address/user_agent/token_used | 审计 |

### 统计视图清单

| 视图 | SQL 技术 | 功能 |
|------|----------|------|
| `v_user_stats` | 多表 LEFT JOIN + GROUP BY | 用户用量概览：对话数、文件数、Token 消耗、消息数、最后登录 |
| `v_daily_stats` | GROUP BY + FILTER + COUNT(DISTINCT) | 每日统计：对话数、总请求、AI 请求、平均延迟、错误数、活跃用户 |

### API 文档

| 端点 | 参数 | 返回数据 | SQL 技术 |
|------|------|----------|----------|
| GET /api/v1/dashboard/overview | — | 对话总数 | 简单 COUNT |
| GET /api/v1/dashboard/stats | start_date, end_date | summary（对话/消息/存储/用户）+ token_consumption（输入/输出/总计/费用估算）+ latency（avg/p50/p95/p99/min/max）+ model_breakdown | 多表 JOIN + percentile_cont() + 聚合 |
| GET /api/v1/dashboard/stats/timeline | start_date, end_date, granularity(daily) | 按天的对话/消息/Token/延迟/文件/用户/错误 time series | generate_series + LEFT JOIN |
| GET /api/v1/dashboard/stats/users | start_date, end_date, limit, sort_by(tokens_used/conversations/messages) | 用户排名列表 | GROUP BY + ORDER BY + LIMIT |

**费用估算公式**：输入 Token × $0.0000005 + 输出 Token × $0.0000015（基于 DeepSeek 定价）。

**延迟百分位**：使用 PostgreSQL `percentile_cont(0.50/0.95/0.99) WITHIN GROUP (ORDER BY latency_ms)` 准确计算分位数。

### 审计日志闭环

```
HTTP 请求 → AuditLoggingMiddleware → 生成 request_id → 记录耗时
  → log_request_to_db() → INSERT INTO operation_logs
  → Dashboard SQL 查询 → 统计聚合 → 前端 Chart.js 展示
```

## 上游依赖

| 上游模块 | 依赖方式 |
|----------|----------|
| 模块一（部署） | docker-compose 将 init.sql 挂载到 postgres 的 `/docker-entrypoint-initdb.d/`，容器启动时自动执行 |
| 模块二（BFF网关） | middleware/logging.py 向 operation_logs 写入审计数据；database.py 提供连接池 |
| 模块三（前端） | 前端 Dashboard 组件通过 dashboardApi 调用本模块的统计接口 |

## 下游对接

| 下游模块 | 对接方式 |
|----------|----------|
| 模块二（BFF网关） | init.sql 创建的 users/file_metadata/conversations/messages 表被模块二的认证路由和文件路由读写 |
| 模块四（AI引擎） | conversations/messages 表被 chat_stream() 生成器读写 |
| 模块三（前端） | 前端 Dashboard 组件展示本模块返回的统计数据 |

## 交付标准

- [ ] init.sql 在 PostgreSQL 容器首次启动时自动执行无错误
- [ ] 7 张表和 2 个视图创建成功，种子数据（admin + demo_user）可用
- [ ] 默认账号可正常登录
- [ ] 管理员访问 GET /api/v1/dashboard/stats 返回完整统计数据
- [ ] 非管理员访问 dashboard 接口返回 40301
- [ ] GET /stats/timeline 补全无数据日期（generate_series 无缺口）
- [ ] GET /stats/users 按 sort_by 参数正确排序
- [ ] 延迟百分位数据准确（p50/p95/p99）
- [ ] operation_logs 表持续有审计日志写入
- [ ] 文件和对话的 deleted_at 软删除 + updated_at 触发器正常工作
