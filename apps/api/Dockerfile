FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -i https://mirror-pypi.liara.ir/simple/ -r requirements.txt

COPY app ./app


# Create a non-root user and group for security
RUN addgroup --system deploy && adduser --system --group deploy

# Transfer ownership of the application directory
RUN chown -R deploy:deploy /app

# Switch to the non-root user
USER deploy

EXPOSE 8000

# Proxy headers required for Nginx to pass real client IPs
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

