FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# 依赖单独一层，利用缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000 8501

# 默认起前端；compose 中按服务覆盖 command
CMD ["streamlit", "run", "web/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
