FROM python:3.12-slim

WORKDIR /app

RUN groupadd -r cloudrag && useradd -r -g cloudrag cloudrag

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY agent_server.py ./agent_server.py
COPY backend/src ./src

RUN mkdir -p /app/knowledge && chown -R cloudrag:cloudrag /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AGENT_PORT=8090 \
    AGENT_KNOWLEDGE_DIR=/app/knowledge

USER cloudrag

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health')" || exit 1

CMD ["sh", "-c", "uvicorn agent_server:app --host 0.0.0.0 --port ${AGENT_PORT:-8090}"]
