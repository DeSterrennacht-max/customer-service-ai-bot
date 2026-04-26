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

当前发布版本：`v1.3.1`

- `v1.3.1`: 修正邮箱自动回复触发条件；用户消息中包含邮箱地址即可按当前 Bot 配置自动回复，不再要求整条消息只有邮箱。
- `v1.3.0`: 图片存储配置改为 Backblaze B2 / S3-compatible 对象存储；Bot 配置新增邮箱格式自动回复，初版支持用户只发送邮箱地址时按 Bot 单独配置自动回复内容。
- `v1.2.0`: 新增 Cloudflare R2 图片存储；FAQ 与知识页支持上传图片并绑定到自动回复，命中后先发送文字再发送图片，后台列表和网页可直接使用 R2 公网图片 URL。
- `v1.1.4`: 优化 FAQ 与知识页列表排版；将拥挤表格改为卡片式信息布局，长答案、正文摘要、问题模式和标签更易阅读。
- `v1.1.3`: Bot 配置页支持按需读取当前 Telegram Bot Description；编辑已有 Bot 时可先从 Telegram 拉取当前说明，再修改并保存，避免盲改和频繁自动读取。
- `v1.1.2`: 调整 Telegram Business 私聊自动回复规则；普通 Bot 私聊未命中时发送可配置兜底回复并转人工，Business 私聊仅在 FAQ/知识库命中时自动回复，未命中不记录、不私聊兜底、不转发客服群；Bot 配置页新增兜底回复和 Bot Description 同步。
- `v1.1.1`: 优化后台机器人列表排版；将拥挤的多列表格改为卡片式信息布局，长欢迎语、Business 接入状态和风险词标签更易阅读。
- `v1.1.0`: 新增 Telegram Business Bot 接入；Business 账号授权后，系统可复用现有 FAQ、知识页、风格化回复和转人工链路，以业务账号身份自动回复私聊。
- `v1.0.8`: 修复入口咨询兜底逻辑；FAQ/知识库未命中时不再返回硬编码业务确认话术，改为转人工并向客户发送转接提示，产品功能/套餐答案由后台 FAQ/知识库维护。
- `v1.0.7`: 改进价格类追问处理；用户先问价格、再补充“2位坐席”等数量时，会优先按上下文计算标准版/高级版合计，并避免重复上一条泛化回复。
- `v1.0.6`: 支持在后台删除 Bot Profile；删除时会先调用 Telegram `deleteWebhook`，再清理该 Bot 关联的 FAQ、知识页、会话、消息、人工工单和风格配置。
- `v1.0.5`: 新增 Bot Profile 保存时自动调用 Telegram `setWebhook`，启用状态的 Bot 会自动注册到生产 webhook 地址，减少新增机器人后的手工配置步骤。
- `v1.0.4`: 修复 OpenAI/LLM 配置无效时 Telegram webhook 返回 500 的问题；当欢迎语/答案润色失败时，自动降级发送原始文本。
- `v1.0.3`: 修复项目内 Nginx 在 API/Web 容器重建后继续使用旧容器 IP，导致 Cloudflare 502 的问题；改为通过 Docker 内置 DNS 动态解析上游服务。
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
- `https://<你的子域名>/telegram/webhook/<bot_username>` -> Telegram webhook

首轮启动可保留：

- `APP_AUTO_CREATE_SCHEMA=true`
- `APP_BOOTSTRAP_DEMO_DATA=true`

完成首轮验证后，把这两个值切回 `false`，再执行：

```bash
cd infra
docker compose --env-file ./env/production.env up -d
```

更完整的 VPS 落地步骤见 `infra/DEPLOY_VPS.md`。

保存启用状态的 Bot Profile 时，后端会自动向 Telegram 注册对应的 `setWebhook`。生产环境必须配置 `APP_PUBLIC_BASE_URL`，或至少配置 `NEXT_PUBLIC_API_BASE_URL` 作为兼容 fallback。

### Backblaze B2 / S3-compatible 图片存储

FAQ 和知识页支持上传图片到 Backblaze B2 或其他 S3-compatible 对象存储，并在自动回复命中时随文字一起发送。生产环境需要先创建 bucket，并配置可公开访问的图片域名，例如 `https://media.example.com`。

需要配置：

```bash
APP_OBJECT_STORAGE_ENDPOINT_URL=https://s3.us-west-004.backblazeb2.com
APP_OBJECT_STORAGE_ACCESS_KEY_ID=<b2-key-id>
APP_OBJECT_STORAGE_SECRET_ACCESS_KEY=<b2-application-key>
APP_OBJECT_STORAGE_BUCKET=customer-service-ai-bot-media
APP_OBJECT_STORAGE_PUBLIC_BASE_URL=https://media.example.com
APP_OBJECT_STORAGE_MAX_IMAGE_BYTES=5242880
```

`APP_R2_*` 旧变量暂时仍可作为兼容 fallback 使用，但新部署建议统一使用 `APP_OBJECT_STORAGE_*`。

## 下一步建议

1. 替换默认 bot token 和 support group chat id。
2. 用 Alembic 正式执行迁移，而不是只依赖自动建表。
3. 填充第一批 FAQ 和知识页数据。
4. 接通 OpenAI 兼容接口，打开语义路由与 humanizer 的真实模型调用。
5. 增加更严格的 webhook 签名校验、审计日志写入和幂等去重。
