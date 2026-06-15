# syntax=docker/dockerfile:1

FROM python:3.12-slim

WORKDIR /app

COPY agent-server-requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r agent-server-requirements.txt

COPY agent_server.py .

RUN mkdir -p /app/knowledge

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AGENT_KNOWLEDGE_DIR=/app/knowledge \
    AGENT_PORT=8090

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8090/health')" || exit 1

CMD ["python", "agent_server.py"]
