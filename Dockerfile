FROM node:22-bookworm-slim AS motion-runtime
WORKDIR /motionlab
COPY editorial_engine/backends/motionlab/package.json editorial_engine/backends/motionlab/package-lock.json ./
RUN npm ci --ignore-scripts --omit=dev

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core libstdc++6 libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt
COPY . .
COPY --from=motion-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=motion-runtime /motionlab/node_modules /app/editorial_engine/backends/motionlab/node_modules
RUN cd /app/editorial_engine/backends/motionlab \
    && node --input-type=module -e 'import "@napi-rs/canvas"; import "three";'
EXPOSE 8000
CMD ["python", "-m", "editor_ultra_app"]
