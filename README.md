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

```bash
cd infra
docker compose up --build
```

对外入口：

- `http://localhost/` -> 管理后台
- `http://localhost/health` -> API 健康检查
- `http://localhost/telegram/webhook` -> Telegram webhook

## 下一步建议

1. 替换默认 bot token 和 support group chat id。
2. 用 Alembic 正式执行迁移，而不是只依赖自动建表。
3. 填充第一批 FAQ 和知识页数据。
4. 接通 OpenAI 兼容接口，打开语义路由与 humanizer 的真实模型调用。
5. 增加更严格的 webhook 签名校验、审计日志写入和幂等去重。
