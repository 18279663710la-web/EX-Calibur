# 模块六：微信多通道接入

## 职责

微信公众号/个人号通道的完整实现：iLink 协议对接、QR 扫码登录、消息轮询与处理、文件 AES-ECB 加密传输、ClawBot 兼容适配。使微信用户能够与 CloudRAG 进行文件问答交互。

## 交付清单

### 代码文件

| 文件 | 说明 |
|------|------|
| `backend/src/services/channels.py` | 通道管理服务（1213行，项目最长模块）：ILinkWeixinClient（iLink HTTP 客户端）+ ChannelManager（通道生命周期）+ AES 加密传输 + 消息处理 + 凭据持久化 |
| `backend/src/routes/channels.py` | 通道管理路由（347行）：GET /channels（列表）、POST /channels（连接/断开）、POST /weixin/qrlogin（扫码登录）、POST /weixin/webhook（事件处理）、handle_weixin_event() 核心处理器 |
| `backend/src/routes/clawbot.py` | ClawBot 兼容路由（160行）：/webhook、/sendmessage、/getupdates 等兼容端点，_process_clawbot_payload() 标准化适配层 |
| `backend/src/services/file_matcher.py` | 文件模糊匹配（被微信通道复用，用于"打开文件"和文本搜索场景） |

### iLink 客户端接口说明

| 操作 | 方法 | 说明 |
|------|------|------|
| 获取二维码 | fetch_qr_code() / get_bot_qrcode() | 从 iLink API 获取登录二维码 |
| 轮询扫码状态 | poll_qr_status() / get_qrcode_status() | 长轮询等待用户扫码确认 |
| 获取消息 | get_updates() | 主动轮询拉取新消息（微信不推送） |
| 发送文本 | send_text() | 向微信用户发送文本回复 |
| 发送文件 | send_file() / send_file_item() | 向微信用户发送文件（先 AES 加密上传 CDN） |
| CDN 上传 | upload_media_to_cdn() | AES-ECB 加密文件 → 上传 → 返回加密参数和密钥 |
| CDN 下载 | download_media_from_cdn() | 下载加密文件 → AES-ECB 解密 → 保存 |

### 消息处理逻辑

| 事件类型 | 处理逻辑 |
|----------|----------|
| **open_file**（打开文件） | 文件名 → file_matcher 模糊匹配 → 找到 → AES 加密上传 CDN → 发送给用户 |
| **text**（文本消息） | 先在 knowledge/ 中模糊搜索匹配文件 → 有匹配则返回选项列表（"第1个: xxx"）→ 无匹配则转发到 Dify 获取 AI 答案 |
| **file**（文件消息） | 从微信 CDN 下载 + AES 解密 → 保存到 knowledge/ → 确认 → 模块五同步脚本后续推送 Dify |
| **序号选择** | 用户输入"打开第X个" → 从之前缓存的文件选项中选择对应文件回传 |

### API 文档

| 端点 | 说明 |
|------|------|
| `GET /api/v1/channels` | 返回所有通道状态（名称、标签、图标、连接状态、运行状态） |
| `POST /api/v1/channels` | `{channel, action: "connect"/"disconnect", config?}` |
| `POST /api/v1/channels/weixin/qrlogin` | `{action: "fetch"/"poll"/"refresh"}` → 返回二维码 data URI / 扫码状态 |
| `POST /api/v1/channels/weixin/webhook` | 接收微信入站事件的标准 Webhook |
| `GET /api/v1/clawbot/weixin-state` | 微信通道运行状态查询 |
| `POST /api/v1/clawbot/webhook` | ClawBot 格式 Webhook |
| `POST /api/v1/clawbot/sendmessage` | 同 webhook |
| `GET\|POST /api/v1/clawbot/getupdates` | 轮询端点 |

### 加密传输说明

```
发送: 文件 → AES-ECB(hash MD5) 加密 → 微信 CDN → 加密查询参数 + AES key → 微信用户
接收: 微信 CDN → 后端下载加密文件 → AES-ECB 解密 → knowledge/
```

加密依赖：`pycryptodome` 库（backend/requirements.txt 中声明）。

## 上游依赖

| 上游模块 | 依赖方式 |
|----------|----------|
| 模块一（部署） | 需要 WEIXIN_BASE_URL、WEIXIN_CDN_BASE_URL、WEIXIN_TOKEN 环境变量 |
| 模块二（BFF网关） | 复用 file_matcher.py 进行知识库文件搜索；使用 get_current_user() 认证 |
| 模块四（AI引擎） | handle_weixin_event 文本消息最终转发到 Dify 查询（调用 services/dify.py） |
| 模块五（文件管线） | 微信上传的文件保存到 knowledge/，由 sync_script 后续推送到 Dify |

## 下游对接

无（微信通道直接面向微信用户，不向其他模块提供接口）。

## 交付标准

- [ ] 微信通道可成功连接（调用 POST /channels {action:"connect"} 获取二维码）
- [ ] QR 扫码后轮询确认成功，通道状态变为 running
- [ ] 微信文本消息 → 知识库模糊搜索 → 返回文件选项列表
- [ ] 微信文本消息 → 无匹配文件 → 转发 Dify → 收到 AI 答案
- [ ] 微信文件消息 → 下载解密 → 保存到 knowledge/ → 确认回复
- [ ] "打开文件"消息 → 匹配文件 → AES 加密上传 CDN → 发送成功
- [ ] 消息去重机制有效（同一消息不重复处理）
- [ ] ClawBot 兼容端点可接收标准格式 Webhook 并正确处理
- [ ] 重启容器后凭据文件自动恢复，微信通道自动重连
