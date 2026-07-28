# syntax=docker/dockerfile:1.4
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN yarn config set registry https://registry.npmjs.org
RUN --mount=type=cache,target=/root/.cache/yarn yarn install --network-timeout 1000000
COPY . .
RUN yarn build

FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
