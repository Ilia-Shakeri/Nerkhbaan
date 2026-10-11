FROM python:3.12.13-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY app ./app

RUN addgroup --system deploy && adduser --system --group deploy
RUN chown -R deploy:deploy /app
USER deploy

CMD ["python", "-m", "app.worker"]
