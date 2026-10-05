# ---- 1. build the web app ---------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build            # -> /src/fusionmap/static

# ---- 2. runtime: CPU-only inference (ONNX Runtime), no PyTorch, no GPU --------------------
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FUSIONMAP_DATA=/data
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY fusionmap ./fusionmap
COPY --from=web /src/fusionmap/static ./fusionmap/static
RUN pip install --no-cache-dir . && useradd -m fusionmap && mkdir -p /data && chown fusionmap /data
USER fusionmap
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["fusionmap", "serve", "--host", "0.0.0.0", "--port", "8000"]
