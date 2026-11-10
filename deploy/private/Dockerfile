FROM node:22-alpine AS panel
WORKDIR /build/panel
COPY apps/panel/package.json apps/panel/package-lock.json ./
RUN npm ci
COPY apps/panel/tsconfig.json apps/panel/vite.config.ts apps/panel/index.html ./
COPY apps/panel/src ./src
RUN npm run build

FROM python:3.13-slim
ARG BUILD_GIT_SHA
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/services/backend/src \
    ALPHASENSE_BUILD_GIT_SHA=${BUILD_GIT_SHA}
WORKDIR /app
RUN python -c "import os,re; assert re.fullmatch(r'(?:[a-f0-9]{40}|[a-f0-9]{64})',os.environ.get('ALPHASENSE_BUILD_GIT_SHA','')), 'Valid BUILD_GIT_SHA is required'"
COPY requirements-dev.lock ./
RUN pip install --no-cache-dir --requirement requirements-dev.lock
COPY pyproject.toml alembic.ini ./
COPY migrations ./migrations
COPY services/backend/src ./services/backend/src
COPY contracts ./contracts
COPY config/provider-policy.json ./config/provider-policy.json
COPY --from=panel /build/panel/dist ./apps/panel/dist
RUN groupadd --gid 10001 research && useradd --uid 10001 --gid 10001 --no-create-home research \
    && mkdir -p /app/.local-postgres/sec-catalog \
    && chown -R 10001:10001 /app/.local-postgres
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["python", "-m", "alphasense.private_runtime"]
CMD ["api"]
