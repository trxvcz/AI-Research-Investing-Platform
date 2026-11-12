FROM node:22-alpine
WORKDIR /app
COPY --chown=node:node . .
RUN mkdir -p artifacts && chown node:node artifacts
USER node
ENV HOST=0.0.0.0 PORT=8080 ARTIFACT_DIR=/app/artifacts
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD node -e "fetch('http://127.0.0.1:8080/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node","services/api/server.mjs"]

