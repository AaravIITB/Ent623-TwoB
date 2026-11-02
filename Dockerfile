# TwoB: one container with the web app and the API.
#   docker build -t taxmind .
#   docker run -p 8000:8000 -v taxmind-data:/data -e TAXMIND_ADMIN_PASSWORD=change-me taxmind
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TAXMIND_DATA=/data
WORKDIR /app
COPY requirements.txt server/requirements.txt ./
RUN pip install --no-cache-dir pandas openpyxl fastapi "uvicorn[standard]" sqlalchemy python-multipart
COPY taxmind/ taxmind/
COPY server/ server/
COPY test_data/ test_data/
COPY --from=web /web/dist web/dist
VOLUME /data
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "taxmind_server.main:app", "--app-dir", "server", "--no-access-log", "--host", "0.0.0.0", "--port", "8000"]
