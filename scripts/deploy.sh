#!/usr/bin/env bash
# 将当前项目同步到 GCP VM，实现「可更新」部署。
# 使用前：在 VM 上已创建目录、安装 Python 并配置 .env（或本机已配置 SSH 与远端路径）。

set -e

# ---------- 配置 ----------
VM_USER="${VM_USER:-$(whoami)}"           # SSH 用户名，GCP 默认与本地用户名一致或需改为实际用户名
VM_HOST="${VM_HOST:?请设置 VM_HOST，例如 VM_HOST=34.80.1.2 ./deploy.sh}"
VM_DIR="${VM_DIR:-/home/$VM_USER/lark-bot-gcp}"   # 远端项目目录

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Deploying from $PROJECT_ROOT to $VM_USER@$VM_HOST:$VM_DIR"

# 同步代码（排除 venv、.env、__pycache__）
rsync -avz --delete \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.venv' \
  --exclude='venv' \
  "$PROJECT_ROOT/" "$VM_USER@$VM_HOST:$VM_DIR/"

echo "Synced. Restarting app on VM..."
ssh "$VM_USER@$VM_HOST" "cd $VM_DIR && (pkill -f 'python.*app.py' 2>/dev/null || true); python3 -m venv .venv 2>/dev/null; . .venv/bin/activate && pip install -q -r requirements.txt && nohup python app.py >> app.log 2>&1 &"
echo "Deploy done. Check: ssh $VM_USER@$VM_HOST 'tail -f $VM_DIR/app.log'"
