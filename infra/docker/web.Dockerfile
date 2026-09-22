FROM node:22.23.2-alpine

WORKDIR /workspace/admin/web

ARG NEXT_PUBLIC_API_BASE_URL

ENV NODE_ENV=production \
    NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

COPY admin/web/package.json admin/web/package-lock.json* ./
RUN npm ci

COPY admin/web /workspace/admin/web

RUN npm run build

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
