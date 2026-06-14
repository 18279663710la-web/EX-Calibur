# CloudRAG-Hub API 接口契约文档 (v1.0.0)

> **角色：成员 3 (后端核心) → 交接给：成员 1 (前端架构) & 全体成员**
>
> **Base URL:** `http://localhost:8080/api/v1`
>
> **最后更新:** 2026-06-09

---

## 目录

1. [通用约定](#1-通用约定)
2. [用户身份认证 (JWT)](#2-用户身份认证-jwt)
3. [文件上传与管理](#3-文件上传与管理)
4. [大数据看板统计](#4-大数据看板统计)
5. [知识库流式对话 (SSE)](#5-知识库流式对话-sse)

---

## 1. 通用约定

### 1.1 请求头规范

| Header | 值 | 说明 |
|--------|-----|------|
| `Content-Type` | `application/json` | 除文件上传外的所有 POST/PUT 请求 |
| `Authorization` | `Bearer <JWT_TOKEN>` | 除登录/注册外的所有接口 |
| `Accept` | `application/json` | 普通接口；SSE 接口使用 `text/event-stream` |
| `X-Request-ID` | `UUID v4` | 可选，用于链路追踪 |

### 1.2 统一响应信封 (Envelope)

所有非 SSE 接口均使用以下格式：

```json
{
  "code": 200,
  "message": "success",
  "data": {},
  "meta": {
    "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "timestamp": "2026-06-09T12:00:00Z",
    "latency_ms": 42
  }
}
```

### 1.3 错误码定义

| HTTP 状态码 | `code` | 说明 |
|-------------|--------|------|
| 400 | 40001 | 参数校验失败 |
| 401 | 40101 | 未认证 (Token 缺失) |
| 401 | 40102 | Token 过期或无效 |
| 403 | 40301 | 权限不足 |
| 404 | 40401 | 资源不存在 |
| 409 | 40901 | 资源冲突 (如重复用户名) |
| 413 | 41301 | 上传文件大小超出限制 |
| 422 | 42201 | 文件类型不支持 |
| 429 | 42901 | 请求过于频繁 |
| 500 | 50001 | 服务器内部错误 |
| 502 | 50201 | 上游 AI 服务不可用 |
| 504 | 50401 | 上游 AI 服务超时 |
| 422 | 50002 | 编码检测/转换失败 |
| 503 | 50003 | Embedding 服务不可用 |
| 402 | 50004 | AI 模型余额不足 |
| 422 | 50005 | 文件内容提取失败 |

### 1.4 分页规范

**请求参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | integer | 1 | 页码，从 1 开始 |
| `page_size` | integer | 20 | 每页条数，最大 100 |

**响应格式：**

```json
{
  "items": [],
  "total": 150,
  "page": 1,
  "page_size": 20,
  "total_pages": 8
}
```

---

## 2. 用户身份认证 (JWT)

### 2.1 用户注册

```
POST /api/v1/auth/register
```

**Request Body:**

```json
{
  "username": "zhangsan",
  "email": "zhangsan@cs.university.edu.cn",
  "password": "SecureP@ss123",
  "confirm_password": "SecureP@ss123"
}
```

**字段校验规则：**
- `username`: 3-32 字符，仅允许字母、数字、下划线
- `email`: 合法邮箱格式，限定 `.edu.cn` 后缀
- `password`: 8-64 字符，必须包含大写、小写、数字、特殊字符中的至少三种
- `confirm_password`: 必须与 `password` 一致

**Success Response (201):**

```json
{
  "code": 201,
  "message": "注册成功",
  "data": {
    "id": "usr_3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "username": "zhangsan",
    "email": "zhangsan@cs.university.edu.cn",
    "avatar_url": "https://www.gravatar.com/avatar/00000000000000000000000000000000?d=identicon",
    "role": "user",
    "created_at": "2026-06-09T12:00:00Z"
  },
  "meta": {
    "request_id": "...",
    "timestamp": "...",
    "latency_ms": 35
  }
}
```

**Error Responses:**

```json
// 409 用户名已存在
{
  "code": 40901,
  "message": "用户名已被占用",
  "data": null
}

// 400 参数校验失败
{
  "code": 40001,
  "message": "密码强度不足：需包含大写、小写、数字、特殊字符中的至少三种",
  "data": null
}
```

---

### 2.2 用户登录

```
POST /api/v1/auth/login
```

**Request Body:**

```json
{
  "username": "zhangsan",
  "password": "SecureP@ss123"
}
```

**Success Response (200):**

```json
{
  "code": 200,
  "message": "登录成功",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c3JfM2ZhODVmNjQtNTcxNy00NTYyLWIzZmMtMmM5NjNmNjZhZmE2IiwidXNlcm5hbWUiOiJ6aGFuZ3NhbiIsInJvbGUiOiJ1c2VyIiwiZXhwIjoxNzE4MDAwMDAwfQ.signature",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.refresh_token_payload",
    "token_type": "Bearer",
    "expires_in": 7200,
    "user": {
      "id": "usr_3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "username": "zhangsan",
      "email": "zhangsan@cs.university.edu.cn",
      "avatar_url": "...",
      "role": "user"
    }
  },
  "meta": { ... }
}
```

**JWT Payload 结构：**

```json
{
  "sub": "usr_3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "username": "zhangsan",
  "role": "user",
  "iat": 1717900000,
  "exp": 1718000000
}
```

**Error Responses:**

```json
// 401 凭证错误
{
  "code": 40101,
  "message": "用户名或密码错误",
  "data": null
}
```

---

### 2.3 获取当前用户信息

```
GET /api/v1/auth/me
Authorization: Bearer <access_token>
```

**Success Response (200):**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "id": "usr_3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "username": "zhangsan",
    "email": "zhangsan@cs.university.edu.cn",
    "avatar_url": "...",
    "role": "user",
    "quota_used_bytes": 104857600,
    "quota_total_bytes": 1073741824,
    "created_at": "2026-06-09T12:00:00Z",
    "last_login_at": "2026-06-09T14:30:00Z"
  },
  "meta": { ... }
}
```

---

### 2.4 刷新 Token

```
POST /api/v1/auth/refresh
Authorization: Bearer <refresh_token>
```

**Request Body:**

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Success Response (200):**

```json
{
  "code": 200,
  "message": "Token 刷新成功",
  "data": {
    "access_token": "eyJ...new_token",
    "refresh_token": "eyJ...new_refresh",
    "token_type": "Bearer",
    "expires_in": 7200
  },
  "meta": { ... }
}
```

---

## 3. 文件上传与管理

### 3.1 文件上传 (拖拽/点击)

```
POST /api/v1/files/upload
Content-Type: multipart/form-data
Authorization: Bearer <access_token>
```

**Form Fields:**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File (binary) | 是 | 待上传文件 |
| `tags` | String | 否 | 逗号分隔的标签，如 `"AI,论文,2026"` |
| `description` | String | 否 | 文件描述，最大 500 字符 |

**文件约束：**
- 最大体积：50MB
- 允许类型：`pdf`, `docx`, `doc`, `txt`, `md`, `csv`, `xlsx`, `pptx`, `png`, `jpg`, `jpeg`, `gif`
- 每个用户总存储配额：1GB

**Success Response (201):**

```json
{
  "code": 201,
  "message": "文件上传成功",
  "data": {
    "id": "file_b9e5a7f0-12ab-4c3d-89ef-0123456789ab",
    "original_name": "云计算综述.pdf",
    "stored_name": "file_b9e5a7f0.pdf",
    "mime_type": "application/pdf",
    "size_bytes": 2485761,
    "size_human": "2.37 MB",
    "url": "/api/v1/files/file_b9e5a7f0-12ab-4c3d-89ef-0123456789ab/download",
    "tags": ["AI", "论文", "2026"],
    "description": "2026年云计算领域综述论文",
    "processing_status": "pending",
    "uploaded_by": "usr_3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "created_at": "2026-06-09T12:00:00Z"
  },
  "meta": { ... }
}
```

> **`processing_status` 说明：**
> - `pending`: 等待向量化处理
> - `processing`: 正在提取文本并向量化
> - `ready`: 已可被知识库检索
> - `failed`: 处理失败（需重新上传）

**Error Responses:**

```json
// 413 文件过大
{
  "code": 41301,
  "message": "文件大小 62.5 MB 超出限制 (最大 50MB)",
  "data": null
}

// 422 类型不支持
{
  "code": 42201,
  "message": "不支持的文件类型 .exe，允许的类型：pdf, docx, doc, txt, md, csv, xlsx, pptx, png, jpg, jpeg, gif",
  "data": null
}

// 413 配额不足
{
  "code": 41301,
  "message": "存储配额不足：已用 980MB / 总量 1GB",
  "data": {
    "quota_used_bytes": 1027604480,
    "quota_total_bytes": 1073741824,
    "file_size_bytes": 52428800
  }
}
```

---

### 3.2 获取文件列表

```
GET /api/v1/files?page=1&page_size=20&keyword=云计算&status=ready&sort_by=created_at&order=desc
Authorization: Bearer <access_token>
```

**Query Parameters:**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | integer | 1 | 页码 |
| `page_size` | integer | 20 | 每页条数 |
| `keyword` | string | — | 搜索文件名 / 描述 |
| `status` | string | — | 过滤处理状态：`pending` / `processing` / `ready` / `failed` |
| `mime_type` | string | — | 按 MIME 类型过滤如 `application/pdf` |
| `sort_by` | string | `created_at` | 排序字段：`created_at` / `size_bytes` / `original_name` |
| `order` | string | `desc` | `asc` 或 `desc` |

**Success Response (200):**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "items": [
      {
        "id": "file_b9e5a7f0-12ab-4c3d-89ef-0123456789ab",
        "original_name": "云计算综述.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 2485761,
        "size_human": "2.37 MB",
        "tags": ["AI", "论文"],
        "description": "2026年云计算领域综述论文",
        "processing_status": "ready",
        "created_at": "2026-06-09T12:00:00Z"
      },
      {
        "id": "file_c8f6b1a2-34cd-5e6f-90ab-1234567890cd",
        "original_name": "大数据架构设计.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size_bytes": 1590482,
        "size_human": "1.52 MB",
        "tags": ["大数据", "架构"],
        "description": "",
        "processing_status": "ready",
        "created_at": "2026-06-08T18:30:00Z"
      }
    ],
    "total": 45,
    "page": 1,
    "page_size": 20,
    "total_pages": 3
  },
  "meta": { ... }
}
```

---

### 3.3 删除文件

```
DELETE /api/v1/files/:file_id
Authorization: Bearer <access_token>
```

**Success Response (200):**

```json
{
  "code": 200,
  "message": "文件已删除",
  "data": {
    "id": "file_b9e5a7f0-12ab-4c3d-89ef-0123456789ab",
    "deleted_at": "2026-06-09T15:00:00Z"
  },
  "meta": { ... }
}
```

**Error Responses:**

```json
// 404
{
  "code": 40401,
  "message": "文件不存在或已被删除",
  "data": null
}
```

---

### 3.4 下载文件

```
GET /api/v1/files/:file_id/download
Authorization: Bearer <access_token>
```

**Response:** 二进制文件流，`Content-Disposition: attachment; filename="云计算综述.pdf"`

---

## 3B. 多模态自动化数据摄入管线 (Pipeline API)

> **Qwen 4B Embedding 驱动：** 本管线使用本地的 Qwen Embedding 4B 模型（2560维），支持大块文本切片（Chunk ≤ 4096 tokens），具有极强的语义抓取能力。

### 3B.1 提交文件到处理管线

```
POST /api/v1/files/pipeline
Content-Type: multipart/form-data
Authorization: Bearer <access_token>
```

**Form Fields:**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File (binary) | 是 | 待处理文件 |
| `tags` | String | 否 | 逗号分隔的标签 |
| `description` | String | 否 | 文件描述 |
| `chunk_separator` | String | 否 | 分段标识符，默认 `\n\n` |
| `chunk_max_length` | Integer | 否 | 分段最大长度（Qwen 4B支持更大块），默认 2000 |
| `chunk_overlap` | Integer | 否 | 分段重叠长度，默认 100 |

**文件约束：**
- 最大体积：200MB（大文件适应音频/扫描件）
- 允许类型：`pdf`, `docx`, `doc`, `txt`, `md`, `csv`, `xlsx`, `pptx`, `png`, `jpg`, `jpeg`, `gif`, `mp3`, `wav`, `m4a`

**处理流程（四步管线路由）：**

```
用户上传文件
    │
    ▼
🛑 步骤1: Encoding Sanitizer
    编码探测(chardet) → GBK/GB2312 → UTF-8 强制转换
    │
    ▼
⚡ 步骤2: Dynamic Router (MIME路由)
    ├─ .txt/.pdf/.docx/.md → Document Extractor (全量文本)
    ├─ .png/.jpg/.jpeg      → Vision Extractor (预留OCR/多模态)
    └─ .mp3/.wav/.m4a       → Audio Extractor (预留ASR)
    │
    ▼
🧬 步骤3: Qwen Embedding 4B (Ollama)
    POST /api/embed → 2560维特征向量
    Chunk Size ≤ 4096 tokens
    │
    ▼
🤖 步骤4: Dify Knowledge Base Sync
    写入文档+分段 → 触发索引 → 同步状态
    │
    ▼
  [完成] processing_status = "ready"
```

**Success Response (202 Accepted):**

```json
{
  "code": 202,
  "message": "文件已提交到处理管线",
  "data": {
    "task_id": "pipe_a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "file_id": "file_xxx",
    "original_name": "实验报告.txt",
    "processing_status": "pending",
    "pipeline_stage": "queued",
    "stages": ["sanitizer", "extractor", "embedding", "syncing"],
    "estimated_seconds": 30,
    "created_at": "2026-06-10T14:00:00Z"
  },
  "meta": { ... }
}
```

**Error Responses:**

```json
// 422 文件类型不支持
{
  "code": 42201,
  "message": "管线不支持的文件类型 .exe",
  "data": null
}

// 413 文件过大
{
  "code": 41301,
  "message": "文件大小 250.0 MB 超出管线限制 (最大 200MB)",
  "data": null
}

// 5002 编码转换失败
{
  "code": 50002,
  "message": "编码检测失败：无法识别文件编码",
  "data": { "detected_encoding": null, "file_name": "corrupt.txt" }
}

// 5003 Embedding 服务不可用
{
  "code": 50003,
  "message": "Qwen Embedding 模型不可用或请求超时",
  "data": null
}

// 5004 AI 模型余额不足 (预留)
{
  "code": 50004,
  "message": "云端模型 API 余额不足 (insufficient_balance)",
  "data": null
}

// 5005 提取失败
{
  "code": 50005,
  "message": "文件内容提取失败：文件可能已损坏",
  "data": null
}
```

---

### 3B.2 查询管线任务状态

```
GET /api/v1/files/pipeline/status/:task_id
Authorization: Bearer <access_token>
```

**Success Response (200):**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "task_id": "pipe_a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "file_id": "file_xxx",
    "original_name": "实验报告.txt",
    "file_size_bytes": 2457600,
    "current_stage": "embedding",
    "stages": {
      "sanitizer": { "status": "completed", "detail": "GBK→UTF-8 转换完成", "duration_ms": 120 },
      "extractor": { "status": "completed", "detail": "提取全文 3450 字符", "duration_ms": 850 },
      "embedding": { "status": "processing", "detail": "正在向量化 (Chunk 3/8)...", "duration_ms": 4200 },
      "syncing": { "status": "pending", "detail": null, "duration_ms": null }
    },
    "overall_status": "processing",
    "embedding_model": "qwen3-embedding:4b",
    "embedding_dimensions": 2560,
    "created_at": "2026-06-10T14:00:00Z",
    "updated_at": "2026-06-10T14:00:05Z"
  },
  "meta": { ... }
}
```

**任务状态流转：**

```
queued → sanitizer → extractor → embedding → syncing → completed
                                                          ↓
                                                       failed
```

**Error Response (404):**

```json
{
  "code": 40401,
  "message": "任务不存在或已过期",
  "data": null
}
```

---

## 4. 大数据看板统计

### 4.1 综合统计数据

```
GET /api/v1/dashboard/stats?start_date=2026-06-01&end_date=2026-06-09
Authorization: Bearer <access_token>
```

**Query Parameters:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `start_date` | string | 是 | 起始日期 `YYYY-MM-DD` |
| `end_date` | string | 是 | 结束日期 `YYYY-MM-DD` |

**Success Response (200):**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "summary": {
      "total_conversations": 3842,
      "total_messages": 28734,
      "total_files_uploaded": 156,
      "total_storage_bytes": 4294967296,
      "total_storage_human": "4.00 GB",
      "active_users": 127
    },
    "token_consumption": {
      "total_tokens": 18765432,
      "total_tokens_human": "18.77M",
      "input_tokens": 5234567,
      "output_tokens": 13530865,
      "avg_tokens_per_conversation": 4884,
      "estimated_cost_usd": 28.15
    },
    "latency": {
      "avg_latency_ms": 847,
      "p50_latency_ms": 620,
      "p95_latency_ms": 2340,
      "p99_latency_ms": 5100,
      "max_latency_ms": 12400,
      "min_latency_ms": 120
    },
    "model_breakdown": [
      {
        "model": "gpt-4o",
        "call_count": 2156,
        "total_tokens": 12034890,
        "avg_latency_ms": 1023
      },
      {
        "model": "gpt-3.5-turbo",
        "call_count": 1136,
        "total_tokens": 4503120,
        "avg_latency_ms": 456
      },
      {
        "model": "claude-3-opus",
        "call_count": 550,
        "total_tokens": 2227422,
        "avg_latency_ms": 1287
      }
    ],
    "period": {
      "start_date": "2026-06-01",
      "end_date": "2026-06-09"
    }
  },
  "meta": { ... }
}
```

**Error Responses (403):**

```json
// 仅管理员可访问
{
  "code": 40301,
  "message": "权限不足：仅管理员可访问看板数据",
  "data": null
}
```

---

### 4.2 时间序列统计 (用于折线图 / 柱状图)

```
GET /api/v1/dashboard/stats/timeline?start_date=2026-06-01&end_date=2026-06-09&granularity=daily
Authorization: Bearer <access_token>
```

**Query Parameters:**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `start_date` | string | 必填 | 起始日期 |
| `end_date` | string | 必填 | 结束日期 |
| `granularity` | string | `daily` | `hourly` / `daily` / `weekly` / `monthly` |

**Success Response (200):**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "granularity": "daily",
    "series": [
      {
        "date": "2026-06-01",
        "conversations": 412,
        "messages": 3120,
        "tokens_used": 2014567,
        "avg_latency_ms": 823,
        "files_uploaded": 18,
        "active_users": 76,
        "errors_count": 3
      },
      {
        "date": "2026-06-02",
        "conversations": 398,
        "messages": 2890,
        "tokens_used": 1876234,
        "avg_latency_ms": 912,
        "files_uploaded": 22,
        "active_users": 81,
        "errors_count": 1
      },
      {
        "date": "2026-06-03",
        "conversations": 456,
        "messages": 3410,
        "tokens_used": 2109845,
        "avg_latency_ms": 801,
        "files_uploaded": 15,
        "active_users": 73,
        "errors_count": 5
      }
    ],
    "period": {
      "start_date": "2026-06-01",
      "end_date": "2026-06-09"
    }
  },
  "meta": { ... }
}
```

---

### 4.3 用户维度统计 (Top N)

```
GET /api/v1/dashboard/stats/users?start_date=2026-06-01&end_date=2026-06-09&limit=10&sort_by=tokens_used
Authorization: Bearer <access_token>
```

**Query Parameters:**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | integer | 10 | 返回前 N 名 |
| `sort_by` | string | `tokens_used` | `tokens_used` / `conversations` / `messages` |

**Success Response (200):**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "users": [
      {
        "user_id": "usr_3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "username": "zhangsan",
        "email": "zhangsan@cs.university.edu.cn",
        "conversations": 89,
        "messages": 672,
        "tokens_used": 523456,
        "files_uploaded": 12,
        "avg_latency_ms": 756,
        "last_active_at": "2026-06-09T14:30:00Z"
      }
    ]
  },
  "meta": { ... }
}
```

---

## 5. 知识库流式对话 (SSE)

> **核心功能：** 这是本系统最重要的接口。后端作为 BFF 层，接收前端对话请求后代理转发至 Dify AI 平台，并将 Dify 返回的 SSE 流实时、安全地透传给前端。后端绝不暴露任何大模型 API Key。

### 5.1 发起知识库检索对话 (SSE 流式返回)

```
POST /api/v1/knowledge-base/chat
Content-Type: application/json
Accept: text/event-stream
Authorization: Bearer <access_token>
```

**Request Body:**

```json
{
  "conversation_id": null,
  "query": "请根据我上传的云计算综述论文，详细解释边缘计算与中心云计算的协作架构是什么？",
  "file_ids": [
    "file_b9e5a7f0-12ab-4c3d-89ef-0123456789ab"
  ],
  "model": "gpt-4o",
  "retrieval_config": {
    "top_k": 5,
    "score_threshold": 0.7,
    "rerank_enabled": true
  },
  "system_prompt_override": null
}
```

**字段说明：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `conversation_id` | string\|null | 否 | 对话 ID，`null` 表示新建对话；传入已有 ID 则续写对话 |
| `query` | string | 是 | 用户提问内容，1-4000 字符 |
| `file_ids` | string[] | 否 | 限定检索的文件范围，空数组 = 检索全部知识库 |
| `model` | string | 否 | 模型选择，默认 `gpt-4o`；可选：`gpt-4o` / `gpt-3.5-turbo` / `claude-3-opus` |
| `retrieval_config.top_k` | integer | 否 | 检索返回的 Top-K 文档片段，默认 5 |
| `retrieval_config.score_threshold` | float | 否 | 相关性阈值 (0-1)，默认 0.7 |
| `retrieval_config.rerank_enabled` | bool | 否 | 是否启用重排序，默认 true |
| `system_prompt_override` | string\|null | 否 | 自定义系统提示词，null 使用默认提示词 |

---

### 5.2 SSE 响应流详解

**Response Headers:**

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

**SSE 事件类型一览：**

| `event` | 含义 | 触发时机 |
|----------|------|----------|
| `meta` | 对话元信息 | 流开始，第一个事件 |
| `references` | 检索到的文档引用 | 在 LLM 回复开始前发送 |
| `message` | LLM 生成的文本 token 增量 | 持续，逐 token 推送 |
| `tool_call` | Agent 工具调用 | (可选) 当模型调用外部工具时 |
| `error` | 错误事件 | 发生错误时 |
| `done` | 流结束，包含完整摘要 | 对话完成时 |

---

### 5.3 逐事件详细定义

#### Event: `meta`

对话元信息，最先发送。

```
event: meta
data: {
  "conversation_id": "conv_7d1e2f3a-4b5c-6789-0def-123456789abc",
  "model": "gpt-4o",
  "created_at": "2026-06-09T15:00:00Z",
  "user_id": "usr_3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

---

#### Event: `references`

检索到的知识库文档片段，在 LLM 开始回复前一次性发送。

```
event: references
data: {
  "chunks": [
    {
      "index": 1,
      "file_id": "file_b9e5a7f0-12ab-4c3d-89ef-0123456789ab",
      "file_name": "云计算综述.pdf",
      "content": "边缘计算与中心云计算的协作架构通常采用'云-边-端'三层模型。边缘节点负责实时数据处理与本地决策，中心云负责全局调度与模型训练...",
      "score": 0.952,
      "page_number": 12
    },
    {
      "index": 2,
      "file_id": "file_b9e5a7f0-12ab-4c3d-89ef-0123456789ab",
      "file_name": "云计算综述.pdf",
      "content": "边缘计算通过在网络边缘侧部署计算资源，有效降低了数据传输延迟。典型的边缘节点包括网关、路由器、微型数据中心等...",
      "score": 0.891,
      "page_number": 13
    }
  ],
  "total_retrieved": 5
}
```

> **前端渲染提示：** 收到此事件后，可在消息气泡上方以折叠卡片形式展示引用来源，用户可点击展开查看原文摘要。

---

#### Event: `message` (逐 Token 流式推送 — 打字机效果)

这是核心事件，AI 生成的每个文本 Token 都会作为独立的 `message` 事件推送。前端需要将这些增量片段**追加**到同一个消息气泡中，实现打字机效果。

```
event: message
data: {"token": "边缘", "index": 0}

event: message
data: {"token": "计算", "index": 1}

event: message
data: {"token": "与", "index": 2}

event: message
data: {"token": "中心", "index": 3}

event: message
data: {"token": "云", "index": 4}

event: message
data: {"token": "计算", "index": 5}

event: message
data: {"token": "的", "index": 6}

event: message
data: {"token": "协作", "index": 7}

event: message
data: {"token": "架构", "index": 8}

event: message
data: {"token": "可以", "index": 9}

event: message
data: {"token": "归纳", "index": 10}

event: message
data: {"token": "为", "index": 11}

event: message
data: {"token": "以下", "index": 12}

event: message
data: {"token": "几个", "index": 13}

event: message
data: {"token": "层面", "index": 14}

event: message
data: {"token": "：\n\n", "index": 15}

event: message
data: {"token": "**", "index": 16}

event: message
data: {"token": "1", "index": 17}

event: message
data: {"token": ".", "index": 18}

event: message
data: {"token": " 网络", "index": 19}

event: message
data: {"token": "层面", "index": 20}

event: message
data: {"token": "**", "index": 21}

event: message
data: {"token": "：", "index": 22}

event: message
data: {"token": "边缘", "index": 23}

event: message
data: {"token": "节点", "index": 24}

... (持续推送直到回答完成)
```

**Token 数据字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `token` | string | 当前增量文本片段（直接追加到消息末尾） |
| `index` | integer | Token 序号，从 0 开始递增 |

> **前端实现注意：**
> - 使用 `EventSource` 或 `fetch() + ReadableStream` 接收事件
> - 将每个 `token` 值直接追加到消息 DOM 元素的 `textContent` 或 `innerText`
> - Markdown 渲染：在流式过程中可暂用纯文本展示，流结束后整体渲染为 Markdown
> - 对于 `"```"` 代码块标记，前端需正确跟踪开/闭状态

---

#### Event: `tool_call` (可选 — Agent 工具调用)

当 AI 需要调用外部工具（如搜索、计算）时触发。

```
event: tool_call
data: {
  "tool_name": "web_search",
  "status": "calling",
  "input": {"query": "边缘计算 2026 发展趋势"},
  "timestamp": "2026-06-09T15:00:03Z"
}

event: tool_call
data: {
  "tool_name": "web_search",
  "status": "completed",
  "input": {"query": "边缘计算 2026 发展趋势"},
  "output": "2026年边缘计算市场规模预计达到XXX亿美元...",
  "duration_ms": 1234,
  "timestamp": "2026-06-09T15:00:04Z"
}
```

> **前端渲染提示：** 可以在消息流中显示一个可折叠的"工具调用状态指示器"，展示工具名称、状态图标 (转圈/完成)、耗时。

---

#### Event: `error`

发生错误时推送，流可能在此事件后终止。

```
event: error
data: {
  "code": 50201,
  "message": "AI 服务暂时不可用，请稍后重试",
  "conversation_id": "conv_7d1e2f3a-4b5c-6789-0def-123456789abc"
}
```

**SSE 流中的错误码：**

| `code` | 说明 |
|--------|------|
| 50001 | 后端内部处理异常 |
| 50201 | 上游 Dify/AI 服务不可用 |
| 50401 | 上游 AI 服务响应超时 (默认 120s) |
| 42901 | AI API 调用频率限制 |
| 40001 | 用户输入被安全审核拦截 |

---

#### Event: `done`

流正常结束，包含本条消息的完整摘要统计。

```
event: done
data: {
  "conversation_id": "conv_7d1e2f3a-4b5c-6789-0def-123456789abc",
  "message_id": "msg_a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "usage": {
    "prompt_tokens": 1245,
    "completion_tokens": 487,
    "total_tokens": 1732
  },
  "latency_ms": 3847,
  "model": "gpt-4o",
  "finished_at": "2026-06-09T15:00:04Z"
}
```

> **前端渲染提示：** 收到 `done` 事件后：
> 1. 将流式累积的文本整体渲染为 Markdown 格式
> 2. 显示"Token 消耗: 1732 | 延迟: 3.85s | 模型: gpt-4o"的脚注
> 3. 更新侧边栏对话列表

---

### 5.4 完整 SSE 流示例 (逐行原始数据)

以下是一次完整对话的 SSE 原始字节流，供前端开发人员理解数据包格式：

```
POST /api/v1/knowledge-base/chat HTTP/1.1
Host: localhost:8080
Content-Type: application/json
Accept: text/event-stream
Authorization: Bearer eyJ...

--- RESPONSE STREAM ---
event: meta
data: {"conversation_id":"conv_7d1e2f3a-4b5c-6789-0def-123456789abc","model":"gpt-4o","created_at":"2026-06-09T15:00:00Z","user_id":"usr_3fa85f64-5717-4562-b3fc-2c963f66afa6"}

event: references
data: {"chunks":[{"index":1,"file_id":"file_b9e5a7f0-12ab-4c3d-89ef-0123456789ab","file_name":"云计算综述.pdf","content":"边缘计算与中心云计算的协作架构通常采用'云-边-端'三层模型...","score":0.952,"page_number":12}],"total_retrieved":5}

event: message
data: {"token":"边缘","index":0}

event: message
data: {"token":"计算","index":1}

event: message
data: {"token":"与","index":2}

... (N 个 message 事件)

event: done
data: {"conversation_id":"conv_7d1e2f3a-4b5c-6789-0def-123456789abc","message_id":"msg_a1b2c3d4-e5f6-7890-abcd-ef1234567890","usage":{"prompt_tokens":1245,"completion_tokens":487,"total_tokens":1732},"latency_ms":3847,"model":"gpt-4o","finished_at":"2026-06-09T15:00:04Z"}
```

---

### 5.5 获取对话历史

```
GET /api/v1/knowledge-base/conversations?page=1&page_size=20
Authorization: Bearer <access_token>
```

**Success Response (200):**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "items": [
      {
        "id": "conv_7d1e2f3a-4b5c-6789-0def-123456789abc",
        "title": "边缘计算与中心云计算的协作架构",
        "model": "gpt-4o",
        "message_count": 6,
        "last_message_preview": "边缘计算与中心云计算的协作架构可以归纳为以下几个层面...",
        "total_tokens": 1732,
        "created_at": "2026-06-09T15:00:00Z",
        "updated_at": "2026-06-09T15:00:04Z"
      }
    ],
    "total": 38,
    "page": 1,
    "page_size": 20,
    "total_pages": 2
  },
  "meta": { ... }
}
```

---

### 5.6 获取单条对话详情 (含完整消息记录)

```
GET /api/v1/knowledge-base/conversations/:conversation_id
Authorization: Bearer <access_token>
```

**Success Response (200):**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "id": "conv_7d1e2f3a-4b5c-6789-0def-123456789abc",
    "title": "边缘计算与中心云计算的协作架构",
    "model": "gpt-4o",
    "messages": [
      {
        "id": "msg_q1",
        "role": "user",
        "content": "请根据我上传的云计算综述论文，详细解释边缘计算与中心云计算的协作架构是什么？",
        "created_at": "2026-06-09T15:00:00Z"
      },
      {
        "id": "msg_a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "role": "assistant",
        "content": "边缘计算与中心云计算的协作架构可以归纳为以下几个层面：\n\n**1. 网络层面**：边缘节点通过...\n\n**2. 数据层面**：...",
        "references": [
          {
            "file_id": "file_b9e5a7f0-12ab-4c3d-89ef-0123456789ab",
            "file_name": "云计算综述.pdf",
            "content": "边缘计算与中心云计算的协作架构...",
            "score": 0.952,
            "page_number": 12
          }
        ],
        "usage": {
          "prompt_tokens": 1245,
          "completion_tokens": 487,
          "total_tokens": 1732
        },
        "latency_ms": 3847,
        "created_at": "2026-06-09T15:00:04Z"
      }
    ],
    "created_at": "2026-06-09T15:00:00Z",
    "updated_at": "2026-06-09T15:00:04Z"
  },
  "meta": { ... }
}
```

---

## 6. 接口清单速查表

| 方法 | 路径 | 说明 | 认证 | SSE |
|------|------|------|------|-----|
| POST | `/api/v1/auth/register` | 用户注册 | — | — |
| POST | `/api/v1/auth/login` | 用户登录 | — | — |
| POST | `/api/v1/auth/refresh` | 刷新 Token | Refresh | — |
| GET | `/api/v1/auth/me` | 当前用户信息 | Bearer | — |
| POST | `/api/v1/files/upload` | 上传文件 | Bearer | — |
| GET | `/api/v1/files` | 文件列表 | Bearer | — |
| DELETE | `/api/v1/files/:id` | 删除文件 | Bearer | — |
| POST | `/api/v1/files/pipeline` | **管线上传**（多模态+编码清洗+Embedding+同步） | Bearer | — |
| GET | `/api/v1/files/pipeline/status/:task_id` | 管线任务状态查询 | Bearer | — |
| GET | `/api/v1/files/:id/download` | 下载文件 | Bearer | — |
| GET | `/api/v1/dashboard/stats` | 综合统计 | Bearer(Admin) | — |
| GET | `/api/v1/dashboard/stats/timeline` | 时序统计 | Bearer(Admin) | — |
| GET | `/api/v1/dashboard/stats/users` | 用户统计 | Bearer(Admin) | — |
| POST | `/api/v1/knowledge-base/chat` | 发起对话 | Bearer | **是** |
| GET | `/api/v1/knowledge-base/conversations` | 对话列表 | Bearer | — |
| GET | `/api/v1/knowledge-base/conversations/:id` | 对话详情 | Bearer | — |

---

## 7. Mock 数据使用说明

前端开发阶段可使用以下 Mock Server 配置：

- **Mock 服务器地址：** `http://localhost:3001` (使用 MSW / json-server / 独立 Mock Server)
- **所有接口响应均符合本文档定义的 Envelope 格式**
- **SSE Mock 建议：** 在后端未就绪时，前端可创建一个模拟 SSE 端点，定时推送预录的 `message` token 流来模拟打字机效果

### SSE Mock 实现参考 (前端自建)

```typescript
// frontend/src/lib/mock/sse-mock.ts
// 模拟 SSE 流式返回，供前端独立开发使用
export function createMockSSE(query: string): ReadableStream<Uint8Array> {
  const mockResponse = "这是一个模拟的 AI 回答，用于前端独立开发。在实际联调时，请将此端点替换为真实后端 API。";
  const tokens = mockResponse.split('');

  return new ReadableStream({
    start(controller) {
      // 1. 发送 meta 事件
      controller.enqueue(encodeSSE('meta', { conversation_id: 'mock_conv_001', model: 'gpt-4o' }));

      // 2. 发送 references 事件
      controller.enqueue(encodeSSE('references', { chunks: [], total_retrieved: 0 }));

      // 3. 逐个 token 推送 (模拟打字机效果)
      let index = 0;
      const interval = setInterval(() => {
        if (index < tokens.length) {
          controller.enqueue(encodeSSE('message', { token: tokens[index], index }));
          index++;
        } else {
          // 4. 发送 done 事件
          controller.enqueue(encodeSSE('done', { conversation_id: 'mock_conv_001', usage: { total_tokens: 42 }, latency_ms: 1200 }));
          controller.close();
          clearInterval(interval);
        }
      }, 50); // 每 50ms 推送一个 token
    }
  });
}
```

---

> **Phase 1 交接确认 —— 成员 3 (后端核心)：**
>
> 以上接口契约文档经过完整设计，覆盖了 CloudRAG-Hub 所需的所有核心接口：
> - JWT 认证体系 (4 个端点)
> - 文件 CRUD 操作 (4 个端点)
> - 大数据看板 (3 个端点)
> - 知识库流式对话 SSE (2 个端点)
>
> 共计 **14 个 API 端点**，包括请求/响应格式、Mock 数据、错误码和 SSE 流式数据包格式。
>
> **请前端团队 (成员 1、成员 2) 基于本文档的 Envelope 与 SSE 格式开始 Mock 开发。**
>
> **请 DBA (成员 4) 基于本文档的实体定义设计数据库表结构。**
