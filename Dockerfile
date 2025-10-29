# --- Frontend build (Vite/React) ---
FROM node:20-alpine AS frontend
WORKDIR /app/frontend

# Copy only package files first for better caching
COPY app/frontend/package*.json ./
RUN npm ci

# Copy the rest of the frontend and build
COPY app/frontend/ ./
RUN npm run build

# --- Backend runtime (FastAPI) ---
FROM python:3.11-slim AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for Google SDKs (grpc, build essentials)
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy backend code and data
COPY app/backend ./app/backend
COPY app/data ./app/data

# Copy built frontend (served as static files by backend if you do that),
# or just to keep in the image for Nginx/static middleware later.
COPY --from=frontend /app/frontend/dist ./app/frontend/dist

# If your FastAPI app file is app/backend/main.py:
EXPOSE 8080
CMD ["uvicorn", "app.backend.main:app", "--host", "0.0.0.0", "--port", "8080"]

