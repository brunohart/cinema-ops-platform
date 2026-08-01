FROM python:3.12-slim

WORKDIR /app

# No pip install — stdlib only in the demo surface (VDE-54)
COPY src/agent/ /app/src/agent/

ENV PYTHONPATH=/app/src
ENV PORT=8080

EXPOSE 8080

RUN groupadd -r demo && useradd -r -g demo -u 10001 demo
USER 10001

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')"

CMD ["python", "-m", "agent.demo_server"]
