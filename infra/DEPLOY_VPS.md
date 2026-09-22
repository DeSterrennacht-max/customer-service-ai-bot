# VPS Deployment

This project is intended to run on a single VPS with Docker Compose, while your host machine keeps owning public `80/443` through its existing Nginx setup.

**Required order: publish the code and tag to GitHub, publish the corresponding non-draft, non-prerelease GitHub Release, verify its commit, and only then deploy that version to the VPS.** This also applies to hotfixes. If publication fails, stop before production deployment. Follow [RELEASE_PROCESS.md](RELEASE_PROCESS.md); never deploy uncommitted or unpublished code.

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
- `APP_PUBLIC_BASE_URL=https://your-domain.example`
- `POSTGRES_PASSWORD`
- `APP_SECRET_KEY`
- `APP_DEFAULT_ADMIN_PASSWORD`
- `APP_DEFAULT_SUPER_ADMIN_PASSWORD`
- `APP_OPENAI_API_KEY`
- `APP_WEBHOOK_SECRET`
- `APP_OBJECT_STORAGE_ENDPOINT_URL`
- `APP_OBJECT_STORAGE_ACCESS_KEY_ID`
- `APP_OBJECT_STORAGE_SECRET_ACCESS_KEY`
- `APP_OBJECT_STORAGE_BUCKET`
- `APP_OBJECT_STORAGE_PUBLIC_BASE_URL`

Keep `APP_AUTO_CREATE_SCHEMA=false` and `APP_BOOTSTRAP_DEMO_DATA=false` for production. Production startup validates these settings and refuses to start if either is enabled. Run migrations before starting the application. For an existing installation, follow the backup and migration sequence in [the maintenance guide](MAINTENANCE_20260922.md).

For FAQ/knowledge-page image replies, create a Backblaze B2 bucket or other S3-compatible bucket and configure a public image domain. Set `APP_OBJECT_STORAGE_PUBLIC_BASE_URL` to that domain, for example `https://media.example.com`.

## 3. Start the stack

```bash
cd /opt/customer-service-ai-bot/infra
docker compose --env-file ./env/production.env up -d --build
```

The command above assumes the database is already migrated. For a new installation, build the images, start only `db redis`, run `alembic upgrade head` from the API image, and bootstrap accounts once in an isolated operator process with `APP_ENV=bootstrap`. Do not enable bootstrap on the production API, Worker, Dispatcher, or Beat services.

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

For releases with database migrations, build the updated API image first, then run Alembic from that image before relying on the new UI:

```bash
cd /opt/customer-service-ai-bot/infra
docker compose --env-file ./env/production.env build api worker web
docker compose --env-file ./env/production.env run --rm api sh -c "cd backend/api && alembic upgrade head"
docker compose --env-file ./env/production.env up -d
```

Expected result:

- `https://your-domain.example/health` returns `{"status":"ok"}`
- the admin UI loads from `/`
- the login page works with the seeded admin account

## 6. Configure Telegram webhook

Saving an active Bot Profile in the admin UI automatically calls Telegram `setWebhook`. The registered webhook uses:

```text
https://your-domain.example/telegram/webhook/<BOT_USERNAME_WITHOUT_AT>
```

Use this manual command only when you need to repair or verify a bot outside the admin UI:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://your-domain.example/telegram/webhook/<BOT_IDENTIFIER>","secret_token":"<APP_WEBHOOK_SECRET>"}'
```

You can inspect the webhook state with:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

## 7. Keep production bootstrap disabled

Keep both bootstrap flags disabled permanently. Use Alembic for schema updates and the operator recovery command in [the maintenance guide](MAINTENANCE_20260922.md) if a super-administrator password is lost.

## 8. Ongoing operations

Deploy updates only after the GitHub Release has been published and verified. The example uses `v1.4.0`; replace it with the new published version. Confirm the checkout is clean and the tag commit matches the verified GitHub commit:

```bash
cd /opt/customer-service-ai-bot
git status --short
git fetch origin tag v1.4.0
git switch --detach v1.4.0
git rev-parse HEAD
```

Complete the release-specific backup and migration steps before starting the updated services (see [the maintenance guide](MAINTENANCE_20260922.md) for v1.4.0):

```bash
cd infra
docker compose --env-file ./env/production.env up -d --build
```

If you are running a version before `v1.0.3`, restart the project Nginx after rebuilding API/Web so it does not keep stale Docker DNS results:

```bash
docker compose --env-file ./env/production.env restart nginx
```

Record the deployed tag, commit, Release URL, backup location, and validation results. Tail logs:

```bash
cd /opt/customer-service-ai-bot/infra
docker compose --env-file ./env/production.env logs -f api worker web nginx
```
