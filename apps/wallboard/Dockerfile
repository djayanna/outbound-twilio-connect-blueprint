FROM node:20-alpine AS build
WORKDIR /app
COPY apps/wallboard/package.json apps/wallboard/package-lock.json ./
RUN npm ci
COPY apps/wallboard/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
RUN printf '%s\n' \
  'server {' \
  '  listen 80;' \
  '  # SSE: longer prefix wins over /api/. Disable buffering so conversation' \
  '  # deltas flush immediately, and raise the read timeout for a long-lived' \
  '  # EventSource connection.' \
  '  location /api/conversations/stream {' \
  '    proxy_pass http://scheduler:3001/conversations/stream;' \
  '    proxy_http_version 1.1;' \
  '    proxy_set_header Connection "";' \
  '    proxy_buffering off;' \
  '    proxy_cache off;' \
  '    proxy_read_timeout 3600s;' \
  '  }' \
  '  location /api/ { proxy_pass http://scheduler:3001/; }' \
  '  location / { root /usr/share/nginx/html; try_files $uri /index.html; }' \
  '}' > /etc/nginx/conf.d/default.conf
EXPOSE 80
