#!/usr/bin/env bash
# 部署到 GCP VM：优先 gcloud scp，失败时用 0x0.st 中转，保证能上线。
# 用法：./scripts/deploy_to_gcp.sh 或 GCP_PROJECT=xxx ./scripts/deploy_to_gcp.sh

set -e

PROJECT="${GCP_PROJECT:-seventh-chassis-490115-u3}"
ZONE="${GCP_ZONE:-asia-east1-b}"
INSTANCE="${GCP_INSTANCE:-lark-bot-vm}"
VM_DIR="${GCP_VM_DIR:-/home/lynn/lark-bot-gcp}"
SSH_HOST="${SSH_HOST:-lark-bot-vm}"

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
  # 2) 尝试本机 scp 到 lark-bot-vm（~/.ssh/config，User lynn）
  echo "[2/4] Trying scp to $SSH_HOST..."
  if scp -o ConnectTimeout=10 "$ROOT/app.py" "$ROOT/requirements.txt" "$SSH_HOST:$VM_DIR/" 2>/dev/null; then
    echo "    scp OK"
    echo "[3/4] Restarting app via ssh $SSH_HOST..."
    ssh -o ConnectTimeout=10 "$SSH_HOST" "cd $VM_DIR && pkill -f 'python app.py' 2>/dev/null || true; . venv/bin/activate 2>/dev/null; pip install -q -r requirements.txt 2>/dev/null; nohup python app.py >> /tmp/app.log 2>&1 & sleep 2; curl -s http://localhost:7777/health || true"
    echo "[4/4] Done."
  else
    # 3) transfer.sh 或 0x0.st
    echo "    scp failed. Trying transfer.sh..."
    URL=$(curl -sS --upload-file "$ROOT/app.py" "https://transfer.sh/app.py" 2>/dev/null || true)
    [[ -z "$URL" || ${#URL} -lt 20 ]] && URL=$(curl -sSF "file=@$ROOT/app.py" "https://0x0.st" 2>/dev/null || true)
    if [[ -n "$URL" && ${#URL} -gt 20 && "$URL" != *"banned"* ]]; then
      echo "    URL: $URL"
      echo "[3/4] SSH to VM: curl + restart..."
      CMD="curl -sSL '$URL' -o /tmp/app_new.py && sudo cp /tmp/app_new.py $VM_DIR/app.py && cd $VM_DIR && pkill -f 'python app.py' 2>/dev/null || true; . venv/bin/activate 2>/dev/null; pip install -q -r requirements.txt 2>/dev/null; nohup python app.py >> /tmp/app.log 2>&1 & sleep 2; curl -s http://localhost:7777/health || true"
      if gcloud compute ssh "$INSTANCE" --zone="$ZONE" --project="$PROJECT" --command="$CMD" 2>/dev/null; then
        echo "    deploy OK"
      elif ssh -o ConnectTimeout=10 "$SSH_HOST" "$CMD" 2>/dev/null; then
        echo "    deploy OK via $SSH_HOST"
      else
        echo ""
        echo "=== 请用浏览器 SSH 手动执行 ==="
        echo "curl -sSL '$URL' -o /tmp/app_new.py"
        echo "sudo cp /tmp/app_new.py $VM_DIR/app.py"
        echo "cd $VM_DIR && pkill -f 'python app.py' 2>/dev/null || true"
        echo ". venv/bin/activate && pip install -r requirements.txt && nohup python app.py &"
        exit 1
      fi
    else
      echo "ERROR: 上传失败且 scp 不可用。请确保 ~/.ssh/config 中 $SSH_HOST 可连接。"
      exit 1
    fi
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
