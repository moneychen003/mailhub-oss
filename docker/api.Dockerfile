FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /opt/mailhub

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY bin ./bin
COPY schema.sql ./

RUN chmod +x /opt/mailhub/bin/*.py

CMD ["sh", "-c", "python /opt/mailhub/bin/bootstrap_runtime.py && uvicorn app.main:app --host 0.0.0.0 --port 8024 --proxy-headers"]
