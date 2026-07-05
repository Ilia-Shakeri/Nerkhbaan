FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN addgroup --system deploy && adduser --system --group deploy
RUN chown -R deploy:deploy /app
USER deploy

CMD ["python", "-m", "app.worker"]
