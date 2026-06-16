FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY knowledge-sync-requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY sync_script.py /app/sync_script.py
COPY knowledge-sync-entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
