FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOST=0.0.0.0 YINGXU_DATA_DIR=/app/private
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY public ./public
COPY workflows ./workflows
EXPOSE 8770
CMD ["python", "server.py"]
