# 模块一：项目总览与部署架构

## 职责

项目全局概念、系统架构设计、Docker 一键部署方案、环境变量配置模板、运维命令文档。

## 交付清单

### 代码文件

| 文件 | 说明 |
|------|------|
| `docker-compose.yml` | 四容器编排（frontend + backend + knowledge-sync + postgres），含网络、卷、健康检查 |
| `.env.example` | 完整环境变量模板（含 JWT、数据库、Dify、DeepSeek、微信通道、上传限制） |
| `backend/Dockerfile` | 后端镜像：Python 3.12-slim，非 root 用户，多阶段构建 |
| `frontend/Dockerfile` | 前端镜像：Node 22 构建 → Nginx 1.27 托管 |
| `knowledge-sync.Dockerfile` | 同步镜像：Python 3.12-slim + 同步依赖 |
| `knowledge-sync-entrypoint.sh` | 同步容器入口：启动运行一次 → 按 SYNC_INTERVAL_SECONDS 循环 |
| `.gitignore` | Git 忽略规则（排除 .env、node_modules、uploads、缓存、构建产物） |

### 文档

| 文档 | 说明 |
|------|------|
| `README.md` | 项目根目录说明文档：功能介绍、运行前准备、Dify 工作流导入、一键启动、微信通道、本地开发指引 |
| **部署说明** | 应包含：环境要求（Docker + Dify 实例）、.env 配置步骤、Dify 工作流导入步骤、启动命令、验证方式、日志查看、故障排查 |

### 配置产物

| 产物 | 说明 |
|------|------|
| `.env` | 实际环境变量文件（从 .env.example 复制并填入真实密钥） |

## 上游依赖

无（模块一是项目起点，所有其他模块依赖此模块的环境配置和容器编排）。

## 下游对接

| 下游模块 | 对接方式 |
|----------|----------|
| 模块二（BFF网关） | docker-compose 启动 backend 容器，挂载 ./knowledge 目录，注入环境变量 |
| 模块三（前端） | docker-compose 启动 frontend 容器，Nginx proxy_pass → backend:8080 |
| 模块五（文件同步） | docker-compose 启动 knowledge-sync 容器，挂载 ./knowledge:ro 和 ./sync_ledger.json |
| 模块七（数据库） | docker-compose 启动 postgres 容器，挂载 init.sql 初始化 Schema |

## 交付标准

- [ ] `docker compose up -d --build` 一键启动成功，4 个容器全部 healthy
- [ ] `http://localhost:8080/health` 返回 `{"status": "healthy"}`
- [ ] `http://localhost:8081` 可以访问前端页面
- [ ] `docker compose logs -f backend` 无启动错误
- [ ] `docker compose logs -f knowledge-sync` 同步容器正常轮询
- [ ] `.env.example` 包含所有必需配置项且无真实密钥
- [ ] README.md 的启动步骤可以复现
