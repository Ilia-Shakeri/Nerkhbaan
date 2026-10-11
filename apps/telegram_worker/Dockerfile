FROM python:3.12.13-alpine3.24

RUN apk upgrade --no-cache

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY app ./app

RUN addgroup -S deploy && adduser -S -G deploy deploy
RUN chown -R deploy:deploy /app
USER deploy

CMD ["python", "-m", "app.worker"]
