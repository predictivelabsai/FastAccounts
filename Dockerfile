FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data

ARG FASTACCOUNTS_COMMIT=""
ARG FASTACCOUNTS_BRANCH=""
ARG FASTACCOUNTS_BUILD_DATE=""
ENV FASTACCOUNTS_COMMIT=$FASTACCOUNTS_COMMIT \
    FASTACCOUNTS_BRANCH=$FASTACCOUNTS_BRANCH \
    FASTACCOUNTS_BUILD_DATE=$FASTACCOUNTS_BUILD_DATE \
    FASTACCOUNTS_PORT=5012 \
    FASTACCOUNTS_DB=/data/fastaccounts.sqlite \
    FASTACCOUNTS_DATA_DIR=/data

EXPOSE 5012
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5012/healthz', timeout=3)"

CMD ["python", "web_app.py"]
