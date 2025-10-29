# --- Frontend build stage ---
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# --- Backend runtime stage ---
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080
WORKDIR /app

# If you need system deps, uncomment and add them
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY backend/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Copy backend code
COPY backend/ /app/

# Copy built frontend to be served as static files
COPY --from=frontend /frontend/dist /app/static

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
