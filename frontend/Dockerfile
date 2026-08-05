# Build with the frontend/ directory as context:
#
#   docker build -f frontend/Dockerfile \
#     --build-arg NEXT_PUBLIC_API_URL=https://<backend-url> \
#     -t automarketing-frontend frontend
#
# Needs next.config.ts's `output: "standalone"` (set for this task) so the
# build stage emits .next/standalone + a minimal server.js that the runtime
# stage can run without node_modules installed.

FROM node:20-slim AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# NEXT_PUBLIC_* vars are inlined into the client bundle at build time, not
# read at container runtime — must arrive as a build ARG, not an ENV set on
# the running Cloud Run service. cloudbuild.yaml passes this from
# substitution _BACKEND_URL.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN npm run build

FROM node:20-slim
WORKDIR /app

COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

ENV PORT=8080
ENV HOSTNAME=0.0.0.0
EXPOSE 8080
CMD ["node", "server.js"]
