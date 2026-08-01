FROM python:3.11-slim

# postgresql-client for psql in seed_platform.sh; build-essential for wheels
# that require a C compiler (e.g. psycopg binary fallback).
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -e ".[dbt]"

ENV PYTHONPATH=/app/src \
    DBT_PROFILES_DIR=/app/dbt \
    DAGSTER_HOME=/dagster_home \
    PYTHONUNBUFFERED=1

RUN mkdir -p /dagster_home
