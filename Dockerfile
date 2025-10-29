# ---------- (optional) FRONTEND BUILD STAGE ----------
# If you have a real Node/Vite React app in app/frontend, this will build it.
# If you DON'T have a Node project there yet, you can comment out this whole stage
# and also remove the COPY --from=frontend lines below.
FROM node:20-alpine AS frontend
WORKDIR /frontend
# Only copy package files first to leverage Docker layer caching
COPY app/frontend/package*.json ./
# If you don't have package.json yet, comment the next two lines
RUN npm ci
COPY app/frontend/ .
# Edit if your build command differs
RUN npm run build

# ---------- BACKEND RUNTIME ----------
FROM python:3.11-slim

# System deps (build tools + curl). Add ffmpeg if you later need local audio ops.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    DATA_ROOT=/app/data \
    CHUNKS_ROOT=/app/data/chunks \
    SYNTHETIC_ROOT=/app/data/synthetic_data \
    CHUNKS_LANG=nl \
    CACHE_ROOT=/app/cache

WORKDIR /app

# Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY app ./app

# Ship data with the image so demo runs instantly (remove if you plan GCS sync)
# If you haven't added data yet, leaving these COPYs is still fine; they no-op.
COPY app/data /app/data
RUN mkdir -p /app/cache/faiss

# (optional) bring in built frontend assets if the first stage ran
# If you commented the frontend stage, comment the next two lines as well.
COPY --from=frontend /frontend/dist /app/frontend/dist

# Expose the FastAPI service
EXPOSE 8080

# Start the API. If your main app file is app/backend/main.py:
CMD ["uvicorn", "app.backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
