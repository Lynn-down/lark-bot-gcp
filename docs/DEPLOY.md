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

## 重要：两套 VM 说明

| SSH Host | IP | 用途 |
|----------|-----|------|
| **lark-bot-vm** | 35.201.186.56 | 飞书机器人（事件 URL: `http://35.201.186.56:7777/event`） |
| gcp-vm | 34.57.230.76 | 其他项目（HSBC Administrator） |

部署脚本默认部署到 lark-bot-vm。若要本机 `scp`/`ssh` 直连，需先把公钥加到 lark-bot-vm：

1. 打开 [Compute Engine → 元数据 → SSH 密钥](https://console.cloud.google.com/compute/metadata/sshKeys?project=seventh-chassis-490115-u3)
2. 添加一项，格式：`lynn:ssh-ed25519 AAA... 你的注释`
3. 保存后即可 `./scripts/deploy_to_gcp.sh`（gcloud 失败时会自动用 scp）

## 手动部署（浏览器 SSH）— 当前脚本无法自动部署时用

1. 打开 https://console.cloud.google.com/compute/instances?project=seventh-chassis-490115-u3
2. 点 **lark-bot-vm** 的 **SSH**
3. 若 VM 上有 git 且代码已 push 到 GitHub：

   ```bash
   cd /home/lynn/lark-bot-gcp
   git pull origin main
   pkill -f 'python app.py' 2>/dev/null || true
   . venv/bin/activate && pip install -q -r requirements.txt
   nohup python app.py >> /tmp/app.log 2>&1 &
   sleep 2 && curl -s http://localhost:7777/version
   ```

4. **若 git 不可用**：在本机执行 `curl -sF "file=@app.py" https://transfer.sh` 拿到 URL，在 VM 执行：

   ```bash
   curl -sSL "把上面拿到的URL粘贴这里" -o /tmp/app_new.py
   cp /tmp/app_new.py /home/lynn/lark-bot-gcp/app.py
   cd /home/lynn/lark-bot-gcp && pkill -f 'python app.py' 2>/dev/null || true
   . venv/bin/activate && nohup python app.py >> /tmp/app.log 2>&1 &
   sleep 2 && curl -s http://localhost:7777/version
   ```

5. **验证部署**：`curl http://35.201.186.56:7777/version` 应返回 `{"version":"v2-wiki-doc-sheets"}`

## 飞书没反应？排查清单

1. **事件 URL**：飞书开发者后台 → 事件订阅 → 请求地址必须是 `http://35.201.186.56:7777/event`（协议用 http，不要 https）
2. **.env**：VM 上 `/home/lynn/lark-bot-gcp/.env` 需包含 `LARK_APP_ID`、`LARK_APP_SECRET`，若开启加密还需 `LARK_ENCRYPT_KEY`、`LARK_VERIFICATION_TOKEN`
3. **权限**：应用需有「接收消息」「发送消息」「获取单聊消息」「获取群消息」等权限，并在后台发布版本
4. **机器人**：需把机器人加入会话（私聊或群聊），并 @ 它或发消息
