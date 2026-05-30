# /opt/Nerkhbaan/Dockerfile

FROM python:3.12-slim

WORKDIR /app

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./requirements.txt

# PIP FALLBACK CHAIN: 
# 1. Primary: Runflare (Iranian)
# 2. Fallback: Tsinghua Tuna (Highly reliable global mirror, ignores US sanctions)
# 3. Fallback: Official PyPI (Direct access)
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://mirror-pypi.runflare.com/simple/ \
    --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple/ \
    --extra-index-url https://pypi.org/simple/

COPY app ./app

EXPOSE 8000

# OPTIMIZATION: Use Uvicorn with multiple workers for production performance to prevent API lag
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
