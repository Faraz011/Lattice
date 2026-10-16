# The demo UI as static files behind nginx (compose only; Render serves it as a static site).
FROM node:20.19-alpine AS build
WORKDIR /ui
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# The API's public address is compiled in. The approver token never is (see check:bundle).
ARG VITE_API_URL=http://localhost:8080
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build && npm run check:bundle

FROM nginx:1.27-alpine
COPY --from=build /ui/dist /usr/share/nginx/html
EXPOSE 80
