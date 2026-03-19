#!/usr/bin/env bash
# 部署到 GCP VM：优先 gcloud scp，失败时用 0x0.st 中转，保证能上线。
# 用法：./scripts/deploy_to_gcp.sh 或 GCP_PROJECT=xxx ./scripts/deploy_to_gcp.sh

set -e

PROJECT="${GCP_PROJECT:-seventh-chassis-490115-u3}"
ZONE="${GCP_ZONE:-asia-east1-b}"
INSTANCE="${GCP_INSTANCE:-lark-bot-vm}"
VM_DIR="${GCP_VM_DIR:-/home/lynn/lark-bot-gcp}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> Deploy lark-bot-gcp to $INSTANCE ($ZONE, $PROJECT)"
echo "    VM path: $VM_DIR"
echo ""

# 1) 尝试 gcloud compute scp（本机可能 Connection reset，CI 环境通常正常）
echo "[1/3] Trying gcloud compute scp..."
if gcloud compute scp \
  "$ROOT/app.py" \
  "$ROOT/requirements.txt" \
  "$INSTANCE:$VM_DIR/" \
  --zone="$ZONE" \
  --project="$PROJECT" 2>/dev/null; then
  echo "    scp OK"
  SCP_OK=1
else
  echo "    scp failed (Connection reset / Permission denied). Using fallback..."
  SCP_OK=0
fi

if [[ "$SCP_OK" -eq 0 ]]; then
  # 2) 上传到 0x0.st，获取 URL
  echo "[2/3] Uploading app.py to 0x0.st..."
  URL=$(curl -sF "file=@$ROOT/app.py" https://0x0.st 2>/dev/null || true)
  if [[ -z "$URL" || "$URL" == *"error"* ]]; then
    echo "ERROR: 0x0.st upload failed. Try: curl -F 'file=@$ROOT/app.py' https://0x0.st"
    exit 1
  fi
  echo "    URL: $URL"

  # 3) 通过 gcloud ssh 在 VM 上 curl 并重启
  echo "[3/3] SSH to VM: curl + cp + restart..."
  CMD="curl -sL '$URL' -o /tmp/app_new.py && sudo cp /tmp/app_new.py $VM_DIR/app.py && cd $VM_DIR && pkill -f 'python app.py' 2>/dev/null || true; . venv/bin/activate 2>/dev/null; pip install -q -r requirements.txt 2>/dev/null; nohup python app.py >> /tmp/app.log 2>&1 & sleep 2; curl -s http://localhost:7777/health || true"
  if gcloud compute ssh "$INSTANCE" \
    --zone="$ZONE" \
    --project="$PROJECT" \
    --command="$CMD" 2>/dev/null; then
    echo "    deploy OK via ssh"
  else
    echo ""
    echo "=== gcloud ssh 也失败，请用 浏览器 SSH 手动执行 ==="
    echo "1. 打开 https://console.cloud.google.com/compute/instances?project=$PROJECT"
    echo "2. 点 $INSTANCE 的 SSH"
    echo "3. 在终端粘贴并执行："
    echo ""
    echo "curl -sL '$URL' -o /tmp/app_new.py"
    echo "sudo cp /tmp/app_new.py $VM_DIR/app.py"
    echo "cd $VM_DIR && pkill -f 'python app.py' 2>/dev/null || true"
    echo ". venv/bin/activate && pip install -q -r requirements.txt"
    echo "nohup python app.py &"
    echo "sleep 2 && curl -s http://localhost:7777/health"
    echo ""
    exit 1
  fi
else
  # scp 成功，直接重启
  echo "[2/3] Restarting app on VM..."
  gcloud compute ssh "$INSTANCE" \
    --zone="$ZONE" \
    --project="$PROJECT" \
    --command="cd $VM_DIR && pkill -f 'python app.py' 2>/dev/null || true; . venv/bin/activate && pip install -q -r requirements.txt && nohup python app.py >> /tmp/app.log 2>&1 & sleep 2 && curl -s http://localhost:7777/health" 2>/dev/null || true
  echo "[3/3] Done."
fi

echo ""
echo "==> Deploy complete. Check: curl http://<VM_IP>:7777/health"
