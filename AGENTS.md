# 项目操作规则

## 发布与部署顺序

所有项目更新（包括紧急修复）必须遵循：**先发布到 GitHub，再部署到 VPS**。

1. 完成修改和必要验证，同步版本号与发布说明。
2. 提交代码并推送到 GitHub 的 `main`，创建并推送对应版本标签。
3. 发布该标签的正式 GitHub Release，确认它不是草稿或预发布，并核对标签对应的提交。
4. 只有上述步骤全部成功，才能在 VPS 部署该 Release 对应的代码或镜像；部署后验证运行状态并记录版本、提交和备份位置。

禁止先修改/部署 VPS，再补推 GitHub 或补建 Release；禁止将未提交的工作区、仅本地存在的提交或未发布的版本部署到生产。GitHub 推送或 Release 发布失败时，停止生产部署。已经发布的标签不得移动，修正内容使用新版本发布。

发布流程见 [infra/RELEASE_PROCESS.md](infra/RELEASE_PROCESS.md)，VPS 操作见 [infra/DEPLOY_VPS.md](infra/DEPLOY_VPS.md)。

## 文件删除

禁止批量删除文件或目录。不要使用 `del /s`、`rd /s`、`rmdir /s`、`Remove-Item -Recurse`、`rm -rf`。

需要删除文件时，只能一次删除一个明确路径的文件。若需要批量删除，应停止操作并请求用户手动删除。
