# Build context = apps/web.
#   docker build -f apps/web/Dockerfile apps/web
FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Vite inlines this at build time; Railway passes service variables as build args.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine
# nginx image renders /etc/nginx/templates/*.template with envsubst (PORT from Railway).
ENV PORT=8080
COPY deploy/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
