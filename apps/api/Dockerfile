FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --no-compile --index-url https://package-mirror.liara.ir/repository/pypi/simple --trusted-host package-mirror.liara.ir -r requirements.txt \
    || pip install --no-cache-dir --no-compile -r requirements.txt

COPY app ./app
COPY db ./db


# Create a non-root runtime account.
RUN addgroup --system deploy && adduser --system --group deploy

RUN chown -R deploy:deploy /app

USER deploy

EXPOSE 8000

# Proxy trust comes from FORWARDED_ALLOW_IPS in the deployment environment.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

