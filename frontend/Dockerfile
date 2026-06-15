# ============================================================
# CloudRAG-Hub Frontend Dockerfile (Multi-stage Build)
# Stage 1: Build Svelte SPA
# Stage 2: Serve via Nginx
# ============================================================

# ---- Stage 1: Build ----
FROM node:22-alpine AS builder

WORKDIR /app

# 依赖缓存层 (利用 Docker layer caching)
# 使用淘宝 npm 镜像加速
RUN npm config set registry https://registry.npmmirror.com
COPY package.json package-lock.json ./
RUN npm ci

# 源码
COPY svelte.config.js vite.config.ts tsconfig.json tsconfig.node.json ./
COPY src/ ./src/
COPY index.html ./
COPY public/ ./public/

# 构建
RUN npm run build

# ---- Stage 2: Nginx ----
FROM nginx:1.27-alpine AS runtime

# 安装 curl 用于健康检查
RUN apk add --no-cache curl

# 清理默认配置
RUN rm -f /etc/nginx/conf.d/default.conf

# 复制自定义 Nginx 配置
COPY nginx.conf /etc/nginx/nginx.conf

# 复制构建产物
COPY --from=builder /app/dist/ /usr/share/nginx/html/

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
