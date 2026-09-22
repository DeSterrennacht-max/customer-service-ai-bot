# 发布流程

**固定顺序：完成验证 → 推送 GitHub 代码与标签 → 发布正式 GitHub Release → 核对发布成功 → 部署 VPS → 验证线上运行。**

此规则适用于所有后续更新和紧急修复。GitHub 是生产版本的来源；推送或 Release 发布失败时，不得继续生产部署。已经发布的标签不能移动，修正需使用新版本。

## 1. 准备版本

- 完成必要测试、构建和迁移验证。
- 同步 `README.md`、`admin/web/package.json`、`admin/web/package-lock.json`、`backend/api/pyproject.toml`、`backend/worker/pyproject.toml` 中的版本号。
- 在 `infra/releases/` 写明变更、验证结果、迁移要求和使用注意事项。
- 确认环境文件、密钥、数据库备份和本地生成文件未进入提交。
- 将审核后的提交以非强制推送方式发布到 GitHub `main`，推送对应标签。若主分支有保护规则，则通过 PR 合并后再打标签。

## 2. 发布 GitHub Release

下面以 `v1.4.0` 为例；后续更新应替换为新版本，不复用旧标签。

```bash
git fetch origin --tags
git tag -a v1.4.0 <已发布到-main-的提交-SHA> -m "v1.4.0"
git push origin refs/tags/v1.4.0
gh release create v1.4.0 --verify-tag --latest \
  --title "v1.4.0" --notes-file infra/releases/v1.4.0.md
gh release view v1.4.0 --json url,tagName,isDraft,isPrerelease,publishedAt
git rev-parse 'v1.4.0^{commit}'
```

发布后确认 Release 页面可读取、`isDraft=false`、`isPrerelease=false`，并从 GitHub 重新核验远程标签对应的提交 SHA。记录 Release 链接和 SHA，然后才进入 VPS 操作。

## 3. 部署已发布版本

在 VPS 先确认工作区干净，再从 GitHub 获取已经核验的版本标签：

```bash
git status --short
git fetch origin tag v1.4.0
git switch --detach v1.4.0
git rev-parse HEAD
```

若存在未提交修改，先查明原因，不得覆盖。核对 `HEAD` 与 GitHub Release 标签对应的 SHA 完全一致后，按照 [DEPLOY_VPS.md](DEPLOY_VPS.md) 和该版本的迁移说明执行备份、构建、迁移、切换与验证。生产构建必须来自已发布的代码；使用预构建镜像时也必须核实其对应提交。

验证应覆盖 HTTPS、登录、数据库迁移、Worker、Beat 和消息队列。交付记录包含 Release 链接、Git SHA、部署时间、备份位置及验证结果。回退只能使用已发布且与现有数据兼容的版本；有新迁移或已接收消息时，先评估数据兼容性。
