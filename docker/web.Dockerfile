FROM node:22-slim AS deps
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.33.2 --activate
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:22-slim AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.33.2 --activate
COPY --from=deps /app/node_modules ./node_modules
COPY web ./
ARG MAILHUB_API_INTERNAL_URL=http://api:8024
ENV NEXT_TELEMETRY_DISABLED=1 \
    MAILHUB_API_INTERNAL_URL=$MAILHUB_API_INTERNAL_URL
RUN pnpm build

FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    MAILHUB_API_INTERNAL_URL=http://api:8024 \
    PORT=3024
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3024
CMD ["node", "server.js"]
