# VPS Deployment

This project is intended to run on a single VPS with Docker Compose, while your host machine keeps owning public `80/443` through its existing Nginx setup.

## 1. Prepare the server

```bash
sudo mkdir -p /opt/customer-service-ai-bot
sudo chown "$USER":"$USER" /opt/customer-service-ai-bot
cd /opt/customer-service-ai-bot
git clone <your-private-repo-url> .
```

Install Docker Engine and the Docker Compose plugin if they are not already present.

## 2. Create the real production env file

```bash
cd /opt/customer-service-ai-bot
cp infra/env/production.env.example infra/env/production.env
```

Edit `infra/env/production.env` and replace every placeholder value before the first boot:

- `NEXT_PUBLIC_API_BASE_URL=https://your-domain.example`
- `POSTGRES_PASSWORD`
- `APP_SECRET_KEY`
- `APP_DEFAULT_ADMIN_PASSWORD`
- `APP_DEFAULT_SUPER_ADMIN_PASSWORD`
- `APP_OPENAI_API_KEY`
- `APP_WEBHOOK_SECRET`

Keep `APP_AUTO_CREATE_SCHEMA=true` and `APP_BOOTSTRAP_DEMO_DATA=true` only for the first successful bootstrap. Switch them both to `false` after the first validated deployment.

## 3. Start the stack

```bash
cd /opt/customer-service-ai-bot/infra
docker compose --env-file ./env/production.env up -d --build
```

The internal services stay private. Only the project Nginx container binds to `127.0.0.1:18081`.

## 4. Configure host Nginx

Use `infra/nginx/vps-reverse-proxy.conf.example` as the template for your host-level Nginx virtual host. It should proxy your public domain to `http://127.0.0.1:18081`.

After adding the site config and certificate, reload host Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 5. Validate the deployment

```bash
curl -I https://your-domain.example
curl https://your-domain.example/health
cd /opt/customer-service-ai-bot/infra
docker compose --env-file ./env/production.env ps
docker compose --env-file ./env/production.env logs -f api worker web nginx
```

Expected result:

- `https://your-domain.example/health` returns `{"status":"ok"}`
- the admin UI loads from `/`
- the login page works with the seeded admin account

## 6. Configure Telegram webhook

Single-bot setup:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://your-domain.example/telegram/webhook","secret_token":"<APP_WEBHOOK_SECRET>"}'
```

Multi-bot setup:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://your-domain.example/telegram/webhook/<BOT_IDENTIFIER>","secret_token":"<APP_WEBHOOK_SECRET>"}'
```

You can inspect the webhook state with:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

## 7. Lock the bootstrap settings

After the admin UI, webhook, and first message flow are verified:

1. Edit `infra/env/production.env`
2. Set `APP_AUTO_CREATE_SCHEMA=false`
3. Set `APP_BOOTSTRAP_DEMO_DATA=false`
4. Restart the stack

```bash
cd /opt/customer-service-ai-bot/infra
docker compose --env-file ./env/production.env up -d
```

## 8. Ongoing operations

Deploy updates:

```bash
cd /opt/customer-service-ai-bot
git pull
cd infra
docker compose --env-file ./env/production.env up -d --build
```

If you are running a version before `v1.0.3`, restart the project Nginx after rebuilding API/Web so it does not keep stale Docker DNS results:

```bash
docker compose --env-file ./env/production.env restart nginx
```

Tail logs:

```bash
cd /opt/customer-service-ai-bot/infra
docker compose --env-file ./env/production.env logs -f api worker web nginx
```
