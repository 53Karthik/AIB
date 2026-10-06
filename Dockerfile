FROM node:22-bookworm-slim AS frontend
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY index.html vite.config.js ./
COPY src ./src
COPY public ./public
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend ./backend
COPY config ./config
COPY Claude_Data ./Claude_Data
COPY --from=frontend /app/dist ./dist
ENV PORT=5174
EXPOSE 5174
CMD ["python", "-m", "backend.server"]
