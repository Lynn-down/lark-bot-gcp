# 部署说明

## 一键部署（推荐）

```bash
./scripts/deploy_to_gcp.sh
```

脚本会先尝试 `gcloud compute scp`，失败则自动用 0x0.st 中转，再通过 `gcloud compute ssh` 在 VM 上拉取并重启。若 ssh 也失败，会打印浏览器 SSH 的手动步骤。

## 环境变量（可选）

| 变量 | 默认值 |
|-----|--------|
| GCP_PROJECT | seventh-chassis-490115-u3 |
| GCP_ZONE | asia-east1-b |
| GCP_INSTANCE | lark-bot-vm |
| GCP_VM_DIR | /home/lynn/lark-bot-gcp |

## GitHub Actions 自动部署

push 到 `main` 后会自动部署。需配置：

1. GCP 控制台创建服务账号，勾选「Compute Engine 管理员」或至少 `compute.instances.get`、`compute.instances.setMetadata`
2. 创建 JSON 密钥，下载
3. GitHub 仓库 → Settings → Secrets and variables → Actions → New repository secret
4. 名称：`GCP_SA_KEY`，内容：粘贴完整 JSON 文件内容

## 推送到 GitHub

若 `git push` 报 `Permission denied (publickey)`，可改用 HTTPS：

```bash
git remote set-url origin https://github.com/Lynn-down/lark-bot-gcp.git
git push -u origin main
```

首次推送会提示输入 GitHub 用户名和 Personal Access Token（需有 repo 权限）。

## 手动部署（浏览器 SSH）

1. 打开 https://console.cloud.google.com/compute/instances?project=seventh-chassis-490115-u3
2. 点 lark-bot-vm 的 **SSH**
3. 上传文件（右上角 ⋮ → Upload file）或本机执行：
   ```bash
   curl -F 'file=@app.py' https://0x0.st
   ```
   拿到 URL 后，在 VM 执行：
   ```bash
   curl -sL "URL" -o /tmp/app.py
   sudo cp /tmp/app.py /home/lynn/lark-bot-gcp/app.py
   cd /home/lynn/lark-bot-gcp && pkill -f "python app.py" 2>/dev/null
   . venv/bin/activate && nohup python app.py &
   ```
