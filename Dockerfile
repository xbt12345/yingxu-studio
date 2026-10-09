FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOST=0.0.0.0 YINGXU_DATA_DIR=/app/private
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY scripts/reviewed_native_seed_limits.py scripts/review75_generation_sizes.py \
    scripts/review84_portrait_controls.py scripts/review86_h3_controls.py \
    scripts/review86_ltx_controls.py scripts/review86_scail_controls.py \
    scripts/review87_video_controls.py scripts/review87_flash_controls.py \
    scripts/review87_infinite_controls.py scripts/review87_output_loops.py ./scripts/
COPY public ./public
COPY workflows ./workflows
EXPOSE 8770
CMD ["python", "server.py"]
