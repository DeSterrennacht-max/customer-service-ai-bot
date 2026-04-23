FROM node:22-alpine

WORKDIR /workspace/admin/web

COPY admin/web/package.json admin/web/package-lock.json* ./
RUN npm install

COPY admin/web /workspace/admin/web

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]
