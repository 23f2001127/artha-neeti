# ArthaNeeti web app: static Vite build served by unprivileged nginx, which also
# proxies /api/* to the backend so the browser talks to a single origin.
# Build from the repository root:  docker build -f docker/frontend.Dockerfile .

FROM node:24-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Leave empty to use the /api proxy; set to call a backend on another origin.
ARG VITE_API_BASE_DIRECT=
ENV VITE_API_BASE_DIRECT=$VITE_API_BASE_DIRECT
RUN npm run build


FROM nginxinc/nginx-unprivileged:stable-alpine
ENV API_UPSTREAM=http://backend:8000
COPY docker/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
