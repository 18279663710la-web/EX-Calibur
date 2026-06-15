# ============================================================
# CloudRAG-Hub Backend Dockerfile
# FastAPI + uvicorn, 非 root 运行
# ============================================================

# ---- Stage 1: Build dependencies ----
FROM python:3.12-slim AS builder

WORKDIR /app

# 构建依赖（使用清华镜像加速）
COPY requirements.txt .
RUN pip install --no-cache-dir --user -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# ---- Stage 2: Runtime ----
FROM python:3.12-slim AS runtime

WORKDIR /app

# 创建非 root 用户
RUN groupadd -r cloudrag && useradd -r -g cloudrag cloudrag

# 从 builder 复制 pip 安装的包
COPY --from=builder /root/.local /home/cloudrag/.local

# 复制源码
COPY src/ ./src/

# 创建上传目录并设置权限
RUN mkdir -p /app/uploads && \
    chown -R cloudrag:cloudrag /app /app/uploads

# 环境变量
ENV PATH="/home/cloudrag/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    POSTGRES_HOST=postgres \
    UPLOAD_DIR=/app/uploads

USER cloudrag

EXPOSE 8080

# 使用 Python 进行健康检查（避免依赖 curl 需要外网下载）
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["sh", "-c", "uvicorn src.main:app --host $HOST --port $PORT"]
