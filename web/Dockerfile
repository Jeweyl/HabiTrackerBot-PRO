# Build Vue SPA
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .
# Same-origin API via nginx proxy — empty base URL
ENV VITE_API_BASE_URL=
RUN npm run build

# Serve with nginx + /api proxy
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
