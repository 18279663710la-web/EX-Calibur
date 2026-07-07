# 模块四：RAG 对话与 AI 引擎

## 职责

Dify AI 平台集成、Chatflow 工作流定义、SSE 流式对话网关、知识库检索配置、检索质量优化策略。这是项目的"AI 大脑"——所有用户提问最终由此模块生成答案。

## 交付清单

### 代码文件

| 文件 | 说明 |
|------|------|
| `EX咖喱棒.yml` | Dify Chatflow 工作流 DSL（1344行）：22 个节点，含问题分类器（4分类）、查询改写器、知识检索（混合搜索 top_k=20 + 重排序）、LLM 答案生成、HTTP 文件操作节点、条件分支 |
| `backend/src/services/dify.py` | Dify API 网关（598行）：DifyGateway 类（文件上传 + 流式请求构建） + chat_stream() SSE 生成器（meta→references→message tokens→done）+ ThinkBlockFilter 过滤 + 参考文献相关性评分排序 |
| `backend/src/routes/chat.py` | 对话路由（247行）：POST /chat/upload（带校验的对话附件上传）+ POST /chat（SSE 流式对话核心端点）+ GET/DELETE /conversations 系列 |
| `backend/src/models/chat.py` | SSE 事件模型（68行）：ChatRequest（请求体）+ SSEMetaEvent + SSEReferencesEvent + SSEMessageToken + SSEToolCallEvent + SSEErrorEvent + SSEDoneEvent |
| `backend/src/services/dynamic_rag.py` | 对话文件上传校验规则（33行）：白名单扩展名、数量/大小/频率限制常量 |

### Dify 工作流节点清单（EX咖喱棒.yml）

| 节点 | 节点ID | 模型/配置 |
|------|--------|-----------|
| start | 1781412217757 | 用户输入接收 |
| question-classifier | 17814123462003 | deepseek-v4-flash，4 类：内容查询/文件操作/按序号打开/文件上传 |
| LLM 2（查询改写器） | 17814123462002 | deepseek-v4-flash, temperature=0.1 |
| knowledge-retrieval | 17814123462000 | multimodal-embedding-v1 + qwen3-rerank, hybrid_search, top_k=20 |
| LLM（答案生成） | 17814123462001 | deepseek-v4-flash, max_tokens=4096, temperature=0.3 |
| LLM 3（文件关键词提取） | 17814123462004 | deepseek-v4-flash, 结构化输出 schema `{"keyword":"string"}` |
| HTTP_Search | 17814123462005 | 调用 agent_server:8080/search |
| HTTP_OPEN 系列 | 17814123462019 / 17814147804610 | 调用 agent_server:8080/open |
| HTTP 请求4（上传） | 1781420964821 | 调用 agent_server:8080/upload |
| 代码执行节点 | 1781415039654 / 1781414690103 / 178141234620110 | 提取文件名数组、按序号索引、精确提取 |
| if-else 分支 | 17814123462006 | count=0 / count=1 / count>1 三分支 |
| answer 节点 | 6 个 | 直接回复出口 |

### API 文档

| 文档 | 说明 |
|------|------|
| **SSE 流式对话协议**（api-contract.md 第 5 节） | 6 种 SSE 事件的完整数据格式：meta（对话元信息）、references（检索引用）、message（逐 Token 推送）、tool_call（工具调用）、error（错误）、done（流结束含 usage/latency） |
| **ChatRequest 请求体** | conversation_id(nullable)、query(1-4000字符)、file_ids[]、model、retrieval_config{top_k, score_threshold, rerank_enabled}、system_prompt_override |
| **Dify 对接说明** | DIFY_BASE_URL 配置方式、API Key 获取方式、工作流导入步骤（Dify 控制台 → 导入 EX咖喱棒.yml → 绑定 Dataset → 发布 → 复制 API Key） |

### 检索优化策略文档

| 文档 | 说明 |
|------|------|
| **知识库检索配置** | 混合搜索权重（向量 0.5/关键词 0.5）、重排序模型 qwen3-rerank、top_k=20 |
| **查询改写策略** | 补充同义词、文件名变体、章节关键词锚点 |
| **分段策略** | model 管线使用 `\n## ` 分隔符、每段 ≤1400 tokens、确保语义完整性 |
| **ThinkBlockFilter 说明** | 过滤 DeepSeek 推理过程中的 `<｜end▁of▁thinking｜>` 标签内容 |

## 上游依赖

| 上游模块 | 依赖方式 |
|----------|----------|
| 模块二（BFF网关） | routes/chat.py 使用 `get_current_user()` 认证；chat_stream() 使用 database.py 连接池读写对话/消息表 |
| 模块五（文件管线） | sync_script.py 向 Dify Dataset 推送清洗后的文件；agent_server 提供 HTTP 文件操作接口供工作流调用 |
| 外部：Dify 服务 | 需要 Dify 实例运行且已导入 EX咖喱棒.yml 并发布 |

## 下游对接

| 下游模块 | 对接方式 |
|----------|----------|
| 模块三（前端） | 前端 ChatView 通过 sse.ts 对接 POST /chat 的 SSE 流 |
| 模块六（微信通道） | handle_weixin_event 的文本消息转发到 Dify 查询 |

## 交付标准

- [ ] EX咖喱棒.yml 可成功导入 Dify 控制台，所有节点连线完整
- [ ] Dify 工作流发布后可正常调用 API
- [ ] POST /api/v1/knowledge-base/chat 返回 SSE 流，6 种事件格式正确
- [ ] 流式响应中包含 knowledge-retrieval 节点的参考文献
- [ ] ThinkBlockFilter 正确过滤 ` response` 标签内的思考过程
- [ ] 参考文献按相关性评分正确排序（用户问题中的文件名出现在 top chunk 中）
- [ ] 对话附件上传（POST /chat/upload）白名单校验有效
- [ ] 对话历史查询（GET /conversations）返回正确的分页数据
- [ ] SSE 流异常断开时返回 error 事件
