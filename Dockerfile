# 配置先: study-support/Dockerfile
#
# gatewayと同じパターン: local-ai-coreを同梱するため、docker-compose側で
#   build:
#     context: ..                    # umbrella repoのルート
#     dockerfile: study-support/Dockerfile
# として呼ぶ想定。
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY local-ai-core /local-ai-core
RUN pip install --no-cache-dir /local-ai-core

COPY study-support/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY study-support/ .

RUN mkdir -p /app/data
RUN useradd -m appuser && chown -R appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STUDY_DB_PATH=/app/data/study.db

EXPOSE 8100

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100"]
