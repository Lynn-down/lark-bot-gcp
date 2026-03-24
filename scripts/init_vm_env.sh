#!/usr/bin/env bash
# init_vm_env.sh  ——  在 VM 上首次初始化 / 更新配置
# 用法：在 VM（Cloud Console SSH 或 gcloud compute ssh）上执行：
#   bash <(curl -sSL https://raw.githubusercontent.com/lynn-down/lark-bot-gcp/main/scripts/init_vm_env.sh)
# 或 git pull 后直接运行：
#   bash scripts/init_vm_env.sh

set -euo pipefail

VM_DIR="${VM_DIR:-$HOME/lark-bot-gcp}"
VENV=".venv"

echo "==> [1/5] 确认项目目录 $VM_DIR"
mkdir -p "$VM_DIR"
cd "$VM_DIR"

echo "==> [2/5] 更新代码（git pull）"
if [ -d .git ]; then
    git pull origin main
else
    echo "    不是 git repo，请先 git clone 或手动上传代码"
    exit 1
fi

echo "==> [3/5] 写入 .env（不覆盖已存在的，除非加 FORCE=1）"
if [ ! -f .env ] || [ "${FORCE:-0}" = "1" ]; then
cat > .env << 'EOF'
# ── 飞书凭证 ──────────────────────────────────────────────────
LARK_APP_ID=cli_a92beaa4c4399ed3
LARK_APP_SECRET=txBH43PGnh0uyGhhprEuPf7akPYyuLjx

# ── 事件订阅加密（若未开启可留空）────────────────────────────
LARK_ENCRYPT_KEY=4rtAbffn36WiFZJkvvlWydULzpkbqhmk
LARK_VERIFICATION_TOKEN=zHMznyp90TxXBptJLB9TqgRCk4h5nCsQ

# ── 服务端口 ────────────────────────────────────────────────
PORT=7777

# ── LLM 配置（已升级为 Claude 3.5 Sonnet）──────────────────
LLM_API_URL=https://api.ablai.top/v1/chat/completions
LLM_API_KEY=REPLACE_WITH_NEW_KEY
LLM_MODEL=claude-3-5-sonnet-20241022
LLM_MAX_TOKENS=2000
EOF
    echo "    .env 已写入。请立即编辑 LLM_API_KEY："
    echo "    nano $VM_DIR/.env"
else
    echo "    .env 已存在，跳过（如需强制覆盖：FORCE=1 bash scripts/init_vm_env.sh）"
fi

echo "==> [4/5] 安装/更新 Python 依赖"
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r requirements.txt
echo "    依赖安装完成"

echo "==> [5/5] 重启服务"
pkill -f 'python.*app\.py' 2>/dev/null || true
sleep 1
nohup "$VENV/bin/python" app.py >> /tmp/app.log 2>&1 &
sleep 4

echo ""
echo "==> 验证..."
if curl -sf http://localhost:7777/health; then
    echo ""
    echo "✅ 服务启动成功！"
    curl -s http://localhost:7777/version
else
    echo "❌ 健康检查失败，查看日志："
    tail -30 /tmp/app.log
fi
