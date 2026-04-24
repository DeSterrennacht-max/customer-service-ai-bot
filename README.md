# Telegram 智能客服机器人 MVP

这是一个基于 `Python + FastAPI + PostgreSQL + Redis + Celery + aiogram + Next.js` 的 Telegram 智能客服机器人第一阶段实现。

## 当前已实现

- FastAPI 后端骨架
- PostgreSQL 数据模型与 Alembic 初始迁移
- Telegram webhook 入口
- 规则路由、语义路由、知识检索、回复链路骨架
- Telegram 客服群人工接管闭环
- FAQ / 知识页 / 会话 / 风格配置管理 API
- Next.js 管理后台基础页面
- Docker Compose + Nginx 部署模板

## 当前版本

当前发布版本：`v1.0.2`

- `v1.0.2`: 修复 Docker API/Worker 镜像缺少 `email-validator` 导致 API 容器启动失败的问题。
- `v1.0.1`: 增加 VPS 单机 Docker Compose 部署方案，支持宿主机 Nginx 反代到 `127.0.0.1:18081`，并补充生产环境变量模板和部署文档。
- `v1.0.0`: 首个 MVP 发布版本，包含 FastAPI 后端、Celery worker、Next.js 管理后台、PostgreSQL/Redis、Telegram webhook 和基础客服流程。

## 目录

- `backend/api`: FastAPI API、数据层、业务服务、路由、提示词
- `backend/worker`: Celery worker 与异步任务
- `admin/web`: Next.js 管理后台
- `shared`: 共享文档与结构定义
- `infra`: Dockerfiles、Compose、Nginx、生产环境模板

## 本地开发

### 1. 后端

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e backend/api
cp backend/api/.env.example backend/api/.env
uvicorn backend.api.app.main:app --reload
```

默认会自动建表并创建一组基础数据：

- 默认管理员：`admin@example.com`
- 默认密码：`ChangeMe123!`
- 默认 bot token：`CHANGE_ME`

你需要把 `bot_profiles.telegram_bot_token` 和 `APP_DEFAULT_SUPPORT_GROUP_CHAT_ID` 换成自己的 Telegram 配置。

### 2. Worker

```bash
source .venv/bin/activate
pip install -e backend/api -e backend/worker
celery -A backend.worker.app.celery_app:celery_app worker --loglevel=INFO
```

### 3. 管理后台

```bash
cd admin/web
npm install
cp .env.example .env.local
npm run dev
```

## Docker Compose 部署

生产环境建议使用单机 `Docker Compose`，再由宿主机现有的 `Nginx` 统一处理域名和 HTTPS。这个仓库已经改成：

- 只让项目内 `nginx` 监听 `127.0.0.1:18081`
- `db`、`redis`、`api`、`web` 不直接暴露到公网
- `web` 容器使用 Next.js 生产构建和 `next start`
- 生产变量从未跟踪的 `infra/env/production.env` 读取

```bash
cd infra
cp env/production.env.example env/production.env
# 编辑 env/production.env，替换域名、密码、OpenAI key、webhook secret
docker compose --env-file ./env/production.env up -d --build
```

对外入口：

- `https://<你的子域名>/` -> 管理后台
- `https://<你的子域名>/health` -> API 健康检查
- `https://<你的子域名>/telegram/webhook` -> Telegram webhook

首轮启动可保留：

- `APP_AUTO_CREATE_SCHEMA=true`
- `APP_BOOTSTRAP_DEMO_DATA=true`

完成首轮验证后，把这两个值切回 `false`，再执行：

```bash
cd infra
docker compose --env-file ./env/production.env up -d
```

更完整的 VPS 落地步骤见 `infra/DEPLOY_VPS.md`。

## 下一步建议

1. 替换默认 bot token 和 support group chat id。
2. 用 Alembic 正式执行迁移，而不是只依赖自动建表。
3. 填充第一批 FAQ 和知识页数据。
4. 接通 OpenAI 兼容接口，打开语义路由与 humanizer 的真实模型调用。
5. 增加更严格的 webhook 签名校验、审计日志写入和幂等去重。
