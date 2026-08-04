FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SPORTS_SUPERMODEL_TIMEZONE=America/New_York

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN python -m pip install --upgrade pip \
    && python -m pip install ".[ui,storage]" \
    && chmod +x deploy/*.sh

EXPOSE 8501
CMD ["bash", "deploy/run-combined.sh"]
