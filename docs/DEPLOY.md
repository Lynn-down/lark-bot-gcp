# 部署说明

## 快速部署

```bash
./scripts/deploy_to_gcp.sh
```

脚本按优先级尝试三种方式：
1. `gcloud compute scp`（CI/CD 环境推荐）
2. 直连 `scp`（本机 `~/.ssh/config` 配置了 `lark-bot-vm`）
3. `transfer.sh` 中转（任何网络均可）

部署后**强制验证** `/health` 端点。若健康检查失败，自动打印最后 30 行日志并给出排查命令。

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GCP_PROJECT` | `seventh-chassis-490115-u3` | GCP 项目 ID |
| `GCP_ZONE` | `asia-east1-b` | VM 区域 |
| `GCP_INSTANCE` | `lark-bot-vm` | 实例名 |
| `GCP_VM_DIR` | `/home/lynn/lark-bot-gcp` | VM 上项目路径 |
| `SSH_HOST` | `lark-bot-vm` | `~/.ssh/config` 别名 |

---

## GitHub Actions 自动部署

push 到 `main` 后自动触发。需配置：

1. GCP 控制台创建服务账号，赋予「Compute Engine 管理员」权限
2. 创建 JSON 密钥并下载
3. GitHub → Settings → Secrets → `GCP_SA_KEY`（粘贴 JSON 全文）

---

## VM 信息

| SSH Host | IP | 用途 |
|----------|-----|------|
| **lark-bot-vm** | 35.201.186.56 | 飞书机器人（事件 URL: `http://35.201.186.56:7777/event`） |
| gcp-vm | 34.57.230.76 | 其他项目 |

---

## 首次在 VM 上初始化

```bash
# 1. 安装依赖
sudo apt-get update -y && sudo apt-get install -y python3 python3-venv

# 2. 进入项目目录
cd ~/lark-bot-gcp

# 3. 创建虚拟环境（统一用 .venv）
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
nano .env    # 填入真实的 LARK_APP_ID, LARK_APP_SECRET 等

# 5. 启动
nohup python app.py >> /tmp/app.log 2>&1 &
sleep 3 && curl -s http://localhost:7777/health
```

---

## 手动部署（浏览器 SSH）

1. 打开 https://console.cloud.google.com/compute/instances?project=seventh-chassis-490115-u3
2. 点 **lark-bot-vm** → **SSH**
3. 在 VM 上执行：

```bash
cd /home/lynn/lark-bot-gcp
git pull origin main
pkill -f 'python.*app.py' || true
. .venv/bin/activate && pip install -q -r requirements.txt
nohup python app.py >> /tmp/app.log 2>&1 &
sleep 3 && curl -s http://localhost:7777/version
```

4. **验证**：`curl http://35.201.186.56:7777/version`
   - 应返回 `{"version":"v5.3-real-docx-contract",...}`

---

## 排查清单（飞书没有回复）

```bash
# 在 lark-bot-vm 上执行：
sudo ss -lntp | grep 7777          # 确认端口监听
ps -ef | grep 'python app.py'      # 确认进程存在
tail -n 200 /tmp/app.log           # 查看最新日志
curl -s http://localhost:7777/health   # 本地健康检查
curl -s http://localhost:7777/version  # 版本核对
```

## 常见问题

| 症状 | 可能原因 | 解法 |
|------|----------|------|
| 端口无监听 | 进程未启动 / 启动失败 | 查 app.log，确认 `.venv/bin/python` 路径正确 |
| ImportError: contract_generator | `contract_generator.py` 未部署 | 重跑 `deploy_to_gcp.sh` |
| 模板文件不存在 | `templates/` 未同步到 VM | `scp -r templates/ lark-bot-vm:~/lark-bot-gcp/` |
| 飞书事件URL不对 | 后台配置错误 | 确认事件URL = `http://35.201.186.56:7777/event` |
| LLM 超时 | 网络或 API Key 问题 | 检查 `.env` 中 `LLM_API_KEY` 和 `LLM_API_URL` |
