FROM python:3.12.13-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --no-compile --require-hashes --index-url https://package-mirror.liara.ir/repository/pypi/simple -r requirements.lock \
    || pip install --no-cache-dir --no-compile --require-hashes -r requirements.lock

COPY app ./app
COPY db ./db


# Create a non-root runtime account.
RUN addgroup --system deploy && adduser --system --group deploy

RUN chown -R deploy:deploy /app

USER deploy

EXPOSE 8000

# Proxy trust comes from FORWARDED_ALLOW_IPS in the deployment environment.
# Bind address and port come from API_HOST/API_PORT so the values Compose sets
# are the values the server actually uses.
ENV API_HOST=0.0.0.0
ENV API_PORT=8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host \"$API_HOST\" --port \"$API_PORT\" --proxy-headers"]

