# 模块五：文件同步与数据处理管线

## 职责

本地知识库文件 → OpenAI-compatible 通用模型智能清洗 → 结构化 Markdown → Dify Dataset 上传的完整数据管线。同时提供本地文件 HTTP 服务，供 Dify 工作流通过 HTTP 节点直接操作本地文件。

## 交付清单

### 代码文件

| 文件 | 说明 |
|------|------|
| `sync_script.py` | 文件同步脚本核心（1230行）：双管线（direct/model）、文本提取（DOCX/PDF/MD/TXT）、OpenAI-compatible 模型清洗、内容保真度校验（SequenceMatcher ≥95%）、检索增强处理（中文标题升级为 ##）、同步账本管理、Dify Dataset 上传 |
| `agent_server.py` | 本地文件 HTTP 服务（153行）：4 个端点（/health、/search、/open、/upload），供 Dify 工作流 HTTP 节点调用 |
| `knowledge-sync.Dockerfile` | 同步容器镜像定义（Python 3.12-slim） |
| `knowledge-sync-entrypoint.sh` | 容器入口脚本：启动时运行一次 → 循环模式（默认 60s 间隔）→ 一次性模式 |
| `knowledge-sync-requirements.txt` | 同步脚本依赖：requests、python-docx、PyPDF2（3 个包） |
| `backend/src/services/file_matcher.py` | 文件名模糊匹配（151行）：rapidfuzz 混合评分（partial_ratio + 有序子序列）+ 中文自然语言查询解析 + 三级精确匹配策略。被 agent_server 和微信通道复用 |

### 双管线对比

| 特性 | direct 管线 | model 管线 |
|------|------------|---------------|
| 参数 | `--pipeline direct` | `--pipeline model` |
| 流程 | 原文件直传 Dify | 提取文本 → 通用模型清洗 → 上传 Markdown |
| 分段 | Dify 自动分段 | 自定义 `\n## ` 分隔，≤1400 tokens |
| 适用 | 纯文本/md 文件 | PDF/DOCX 等排版复杂文件 |

### 模型清洗规则文档

| 规则类别 | 说明 |
|----------|------|
| **实验报告类** | 严格保留实验目的、步骤、数据、命令日志、结论 |
| **实验模板类** | 保留引导性文字和占位符（如 `[请在此处填写]`） |
| **架构设计类** | 侧重组件关系、协议流程、配置项 |
| **章节锚点拼接** | 公式：`## [父级大板块标题] - [子序号] [子标题]`；多层嵌套逐级传递 |
| **表格修复** | Tab 分隔 → 标准 Markdown 线性表格（`| A | B |`） |
| **代码块** | 强制围栏包裹并指定语言 |
| **噪声消除** | 剔除页眉页脚、页码、水印、签名栏 |
| **保真度校验** | SequenceMatcher 对比清洗前后，低于 95% 回退到保留原文模式 |

### 同步账本机制说明

| 特性 | 说明 |
|------|------|
| 存储位置 | `sync_ledger.json`（docker-compose 挂载到 `/app/state/`） |
| 数据结构 | `{files: {路径: {sha256, size, status, document_id, pipeline_version}}, whitelist: {}}` |
| 增量检测 | SHA256 + size 双校验，仅上传变化文件 |
| 远程对账 | 拉取 Dify Dataset 已有文档 → 匹配本地 → 自动同步状态 |
| 版本追踪 | pipeline_version 升级后触发全量重建 |

### API 文档

| 端点 | 说明 |
|------|------|
| `GET /health` | agent_server 健康检查 |
| `POST /search` | 模糊搜索文件：`{keyword, top_k}` → 返回匹配文件列表（含文件名、路径、评分） |
| `POST /open` | 打开文件：`{filename}` → 调用 OS 打开或返回路径 |
| `POST /upload` | 多文件上传：`multipart files[]` → 保存到 knowledge/，返回成功/失败计数 |

## 上游依赖

| 上游模块 | 依赖方式 |
|----------|----------|
| 模块一（部署） | docker-compose 提供 LOCAL_FILE_DIR、DIFY_DATASET_API_KEY、CLEANING_MODEL_API_KEY 等环境变量 |
| 外部：Dify Dataset | 需要配置 DIFY_DATASET_ID 和 DIFY_DATASET_API_KEY |
| 外部：OpenAI-compatible 模型 API | 需要配置 CLEANING_MODEL_API_KEY、CLEANING_MODEL_BASE_URL、CLEANING_MODEL_NAME（model 管线必需） |

## 下游对接

| 下游模块 | 对接方式 |
|----------|----------|
| 模块四（AI引擎） | Dify 工作流的 knowledge-retrieval 节点从此模块推送的 Dataset 中检索；HTTP_Search/HTTP_OPEN 节点调用 agent_server |
| 模块六（微信通道） | agent_server 的 /upload 端点被微信文件上传功能复用；file_matcher 被微信文本搜索复用 |
| 模块二（BFF网关） | file_matcher.py 被后端路由直接引用 |

## 交付标准

- [ ] `python sync_script.py --source-dir knowledge --pipeline direct --dry-run` 正确列出待上传文件
- [ ] `python sync_script.py --source-dir knowledge --pipeline model` 正确清洗 DOCX/PDF 并输出 Markdown
- [ ] 清洗后的 Markdown 与原文相似度 ≥95%
- [ ] 同步账本增量检测正确：未修改文件不重复上传
- [ ] agent_server 启动后 /health 正常响应
- [ ] POST /search 对中文关键词返回正确模糊匹配结果
- [ ] POST /upload 成功写入文件到 knowledge/ 目录
- [ ] Docker 中 knowledge-sync 容器按配置间隔自动同步
