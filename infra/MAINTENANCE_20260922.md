# 2026-09-22 maintenance release

This release pins Python 3.12.14, Node 22.23.2, Next.js 15.5.25, PostgreSQL 16.15,
Redis 7.4.11, and nginx 1.30.5. The frontend lock also patches PostCSS, nanoid, and
sharp without changing the requested Next.js major version. Python application
dependencies retain the installed production versions in `backend/requirements.lock`;
upgrading their separate advisories is a subsequent dependency change.

## Behavior

- `APP_ENV=production` and `APP_NAME` are read as documented. API/Worker startup
  refuses missing production secrets, automatic schema creation, or demo bootstrap.
- Build contexts exclude environments, Git metadata and local dependencies; images
  copy only application directories. The frontend receives no backend secret env file.
- Webhooks persist a unique `(bot_profile_id, update_id)` before acknowledging receipt.
  Inbox processing commits customer messages, takeover changes, and outbound records
  together. Per-bot transaction locks serialize processing and protect conversation creation.
- A separate dispatcher consumes the control queue so model latency cannot starve
  incoming-message processing. One Beat instance schedules inbox/outbox recovery and
  releases handoffs after eight hours without another customer message.
- Outbound parts are sent in order under a per-conversation advisory lock. Known
  Telegram rate limits retry with backoff and a maximum attempt count. Permanent
  failures stay visible. Network timeouts and interrupted sends become `uncertain`:
  Telegram has no idempotency key, so these are never blindly resent. Operators can
  verify the chat and explicitly resend unsuccessful parts from conversation details.
  Successful parts are retained and not resent. Historical failed messages are not
  automatically replayed.
- Manual takeover queues a support-group notice when a group is configured. Both
  regular and Business conversations stop new automatic replies while handed off.
  High-risk knowledge transfers regular chats to support; Business mode preserves its
  existing silent behavior for high-risk/unmatched messages.
- Group identity includes both bot and chat. Existing group message chat IDs are
  backfilled from their handoff ticket in the migration.
- Password changes/resets revoke all sessions. Refresh tokens rotate on use; logout
  revokes the current session. Old pre-release tokens require a fresh login. Account
  passwords are not changed by deployment. Login attempts are limited per account.
- Existing bots cannot be moved between tenants by editing their tenant ID.

## Deployment

For all future deployments, first publish and verify the code, tag, and formal
GitHub Release as required by [RELEASE_PROCESS.md](RELEASE_PROCESS.md). Only then
deploy its exact commit to the VPS. The original 2026-09-22 maintenance deployment
preceded this rule; v1.4.0 records that already-deployed maintenance release.

1. Run unit and isolated PostgreSQL integration tests, then build the images. The
   integration suite only runs with `CSB_INTEGRATION_TESTS=1`, `APP_ENV=test`, and
   database name `csb_test`. Never point that suite at the production database.
2. Record existing image IDs and the previous Git revision; retain the current env
   file with mode 600. Briefly close the project ingress and stop API/workers so a
   fresh `pg_dump -Fc` and Redis snapshot form a consistent maintenance checkpoint.
3. Upgrade PostgreSQL/Redis within their pinned major versions and wait for readiness.
4. Run `alembic upgrade head` from the new API image (`backend/api` directory).
   Expected revision is `20260922_0011`. Inspect counts and validate startup config.
5. Start API, web, worker, dispatcher, and exactly one Beat; validate API/worker
   readiness, then restore the nginx ingress and validate HTTPS and login.
6. Check pending/failed inbox updates and outbound deliveries, worker registration,
   and the first Beat executions. The admin UI exposes delivery results and manual
   retry; uncertain outcomes require explicit operator confirmation.

The migration is additive and deliberately does not provide a destructive downgrade.
Before opening ingress, rollback can use the saved images/revision and checkpoint.
After new updates have been accepted, prefer a forward fix: preserve/drain the inbox
and reconcile outbound records before considering an older application version.
Older code does not understand the new delivery statuses or session revocations;
an unconditional application rollback after traffic resumes is unsafe. Do not run
`docker compose down -v`, prune images, or delete backup directories.

## Super-administrator recovery

On the authorized host, using the current production environment:

```bash
docker compose --env-file ./env/production.env exec api \
  python -m backend.api.app.cli reset-superadmin --username EXISTING_USERNAME
```

The command accepts an existing active super-administrator only. It prompts twice
without echoing the new password and revokes old sessions. Passwords need at least
12 characters, letters and digits, and no more than 72 UTF-8 bytes. Do not put a
password in command-line arguments or chat logs.

New installations must run migrations first. Bootstrap, if needed, is an isolated
operator command with explicit non-production settings and populated secret values;
production service startup never enables demo bootstrap.
