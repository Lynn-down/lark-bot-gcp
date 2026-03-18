#!/usr/bin/env bash
# 在 Google Cloud 上创建一台 VM，用于部署 Lark 事件订阅服务。
# 使用前：安装 gcloud CLI 并执行 gcloud init、gcloud auth login。

set -e

# ---------- 可修改配置 ----------
# 优先用环境变量 GCP_PROJECT_ID，否则用当前 gcloud 配置的项目（先执行 gcloud config set project 你的项目ID）
PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" ]]; then
  echo "ERROR: No GCP project set. Run: gcloud config set project YOUR_PROJECT_ID"
  echo "  Or set env: GCP_PROJECT_ID=YOUR_PROJECT_ID"
  echo "  List your projects: gcloud projects list"
  exit 1
fi

# 实例名和区域可以根据需要改
INSTANCE_NAME="${GCP_INSTANCE_NAME:-lark-bot-vm}"
ZONE="${GCP_ZONE:-asia-east1-b}"              # 台湾区域，可选 asia-northeast1-b 等
MACHINE_TYPE="${GCP_MACHINE_TYPE:-e2-micro}"  # 免费档 e2-micro，或 e2-small
BOOT_DISK_SIZE="10GB"

# 创建 VM（带外部 IP，供飞书回调访问）
echo "Creating VM: $INSTANCE_NAME in $ZONE (project: $PROJECT_ID)"
gcloud compute instances create "$INSTANCE_NAME" \
  --project="$PROJECT_ID" \
  --zone="$ZONE" \
  --machine-type="$MACHINE_TYPE" \
  --boot-disk-size="$BOOT_DISK_SIZE" \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --tags=allow-lark-webhook,http-server \
  --metadata=startup-script='#!/bin/bash
apt-get update -y
apt-get install -y python3 python3-pip python3-venv
'

# 开放 SSH（22）和 HTTP（80、7777）流量
echo "Creating firewall rule for SSH, HTTP (80) and app port (7777)..."
gcloud compute firewall-rules create allow-lark-webhook \
  --project="$PROJECT_ID" \
  --allow=tcp:22,tcp:80,tcp:7777 \
  --target-tags=allow-lark-webhook \
  --source-ranges=0.0.0.0/0 \
  --description="Allow SSH and Lark event webhook" 2>/dev/null || true

echo "Done. Get external IP with:"
echo "  gcloud compute instances describe $INSTANCE_NAME --zone=$ZONE --format='get(networkInterfaces[0].accessConfigs[0].natIP)'"