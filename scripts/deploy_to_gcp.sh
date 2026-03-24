#!/usr/bin/env bash
# deploy_to_gcp.sh  ——  部署到 GCP VM
# 优先 gcloud compute scp，失败时用直连 scp，再失败用 transfer.sh 中转。
# 部署后强制验证 /health 端点，确认进程真正跑起来。
#
# 用法：
#   ./scripts/deploy_to_gcp.sh
#   GCP_PROJECT=xxx GCP_ZONE=yyy ./scripts/deploy_to_gcp.sh
#
# 依赖：gcloud（可选）、ssh/scp 或网络可达 VM

set -euo pipefail   # 严格模式：任何命令失败立即退出，禁止未声明变量

PROJECT="${GCP_PROJECT:-seventh-chassis-490115-u3}"
ZONE="${GCP_ZONE:-asia-east1-b}"
INSTANCE="${GCP_INSTANCE:-lark-bot-vm}"
VM_DIR="${GCP_VM_DIR:-/home/lynn/lark-bot-gcp}"
SSH_HOST="${SSH_HOST:-lark-bot-vm}"      # ~/.ssh/config 中的别名
VENV=".venv"                              # 统一使用 .venv（与 setup_vm_first_time.sh 一致）

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 部署的文件列表（不含 .env，不含临时文件）
DEPLOY_FILES=(
    app.py
    contract_generator.py
    roster_module.py
    email_sender.py
    llm_client_v2.py
    fallback_reply.py
    requirements.txt
    company_info.json
    roster.json
)

echo "==> 部署 lark-bot-gcp 到 $INSTANCE ($ZONE, $PROJECT)"
echo "    VM 目录: $VM_DIR"
echo "    虚拟环境: $VENV"
echo ""

# ── 内部函数：在 VM 上重启并验证 ──────────────────────────────────────────────
restart_and_verify() {
    local ssh_cmd="$1"   # 执行远程命令的方式，如 "ssh lark-bot-vm" 或 "gcloud compute ssh ..."
    echo "[restart] 停止旧进程..."
    $ssh_cmd "pkill -f 'python.*app\.py' || true"
    sleep 1

    echo "[restart] 同步依赖..."
    $ssh_cmd "cd $VM_DIR && $VENV/bin/pip install -q -r requirements.txt" || {
        echo "[restart] pip install 失败，尝试重建虚拟环境..."
        $ssh_cmd "cd $VM_DIR && python3 -m venv $VENV && $VENV/bin/pip install -q -r requirements.txt"
    }

    echo "[restart] 启动 app.py..."
    $ssh_cmd "cd $VM_DIR && nohup $VENV/bin/python app.py >> /tmp/app.log 2>&1 &"
    sleep 3

    echo "[restart] 验证 /health..."
    local health
    health=$($ssh_cmd "curl -sf http://localhost:7777/health 2>&1") || {
        echo "!!! 健康检查失败 —— 抓取最后 30 行日志 !!!"
        $ssh_cmd "tail -n 30 /tmp/app.log" || true
        echo ""
        echo "请登录 VM 手动排查："
        echo "  sudo ss -lntp | grep 7777"
        echo "  ps -ef | grep 'python app.py'"
        echo "  tail -n 100 /tmp/app.log"
        return 1
    }
    echo "[OK] /health 响应: $health"
    return 0
}

# ── 传输文件 ──────────────────────────────────────────────────────────────────
TRANSFER_OK=0

# 方式1：gcloud compute scp（CI/CD 环境推荐）
if command -v gcloud &>/dev/null; then
    echo "[1/3] 尝试 gcloud compute scp..."
    FILES_ABS=()
    for f in "${DEPLOY_FILES[@]}"; do FILES_ABS+=("$ROOT/$f"); done
    # 同时传 templates/ 目录
    if gcloud compute scp \
        "${FILES_ABS[@]}" \
        "$INSTANCE:$VM_DIR/" \
        --zone="$ZONE" --project="$PROJECT"; then
        # 传模板目录
        gcloud compute scp --recurse \
            "$ROOT/templates" \
            "$INSTANCE:$VM_DIR/" \
            --zone="$ZONE" --project="$PROJECT" || true
        echo "    [gcloud scp OK]"
        TRANSFER_OK=1
        SSH_CMD_RUNNER="gcloud compute ssh $INSTANCE --zone=$ZONE --project=$PROJECT --command"
    else
        echo "    [gcloud scp 失败，尝试下一方式]"
    fi
fi

# 方式2：直连 scp（本机 ~/.ssh/config 配置了 lark-bot-vm）
if [[ "$TRANSFER_OK" -eq 0 ]] && ssh -o ConnectTimeout=8 -o BatchMode=yes "$SSH_HOST" true 2>/dev/null; then
    echo "[2/3] 尝试直连 scp 到 $SSH_HOST..."
    FILES_ABS=()
    for f in "${DEPLOY_FILES[@]}"; do FILES_ABS+=("$ROOT/$f"); done
    if scp -o ConnectTimeout=10 "${FILES_ABS[@]}" "$SSH_HOST:$VM_DIR/"; then
        scp -rp "$ROOT/templates" "$SSH_HOST:$VM_DIR/" || true
        echo "    [scp OK]"
        TRANSFER_OK=1
        SSH_CMD_RUNNER="ssh -o ConnectTimeout=10 $SSH_HOST"
    else
        echo "    [scp 失败]"
    fi
fi

# 方式3：transfer.sh 中转（只传 app.py + contract_generator.py + requirements.txt）
if [[ "$TRANSFER_OK" -eq 0 ]]; then
    echo "[3/3] 使用 transfer.sh 中转关键文件..."
    declare -A UPLOAD_URLS
    for f in app.py contract_generator.py requirements.txt; do
        URL=$(curl -sS --upload-file "$ROOT/$f" "https://transfer.sh/$f") || \
        URL=$(curl -sSF "file=@$ROOT/$f" "https://0x0.st")
        if [[ -n "$URL" && ${#URL} -gt 20 && "$URL" != *"banned"* ]]; then
            UPLOAD_URLS["$f"]="$URL"
            echo "    $f → $URL"
        else
            echo "ERROR: $f 上传失败。请检查网络或手动部署。"
            exit 1
        fi
    done

    FETCH_CMD=""
    for f in "${!UPLOAD_URLS[@]}"; do
        FETCH_CMD+="curl -sSL '${UPLOAD_URLS[$f]}' -o /tmp/_${f} && sudo cp /tmp/_${f} $VM_DIR/$f; "
    done

    if command -v gcloud &>/dev/null; then
        gcloud compute ssh "$INSTANCE" --zone="$ZONE" --project="$PROJECT" --command="$FETCH_CMD"
        SSH_CMD_RUNNER="gcloud compute ssh $INSTANCE --zone=$ZONE --project=$PROJECT --command"
    elif ssh -o ConnectTimeout=8 -o BatchMode=yes "$SSH_HOST" true 2>/dev/null; then
        ssh -o ConnectTimeout=10 "$SSH_HOST" "$FETCH_CMD"
        SSH_CMD_RUNNER="ssh -o ConnectTimeout=10 $SSH_HOST"
    else
        echo ""
        echo "=== 自动部署失败，请在浏览器 SSH（Cloud Console）中手动执行 ==="
        for f in "${!UPLOAD_URLS[@]}"; do
            echo "curl -sSL '${UPLOAD_URLS[$f]}' -o /tmp/_${f} && sudo cp /tmp/_${f} $VM_DIR/$f"
        done
        echo "cd $VM_DIR && pkill -f 'python.*app.py' || true"
        echo "$VENV/bin/pip install -r requirements.txt"
        echo "nohup $VENV/bin/python app.py >> /tmp/app.log 2>&1 &"
        echo "curl -sf http://localhost:7777/health"
        exit 1
    fi
    TRANSFER_OK=1
fi

# ── 重启 + 验证 ───────────────────────────────────────────────────────────────
echo ""
echo "==> 重启并验证..."

# 包装成统一调用格式
_ssh_exec() {
    if [[ "$SSH_CMD_RUNNER" == gcloud* ]]; then
        gcloud compute ssh "$INSTANCE" \
            --zone="$ZONE" --project="$PROJECT" \
            --command="$1"
    else
        $SSH_CMD_RUNNER "$1"
    fi
}

restart_and_verify "_ssh_exec"

echo ""
echo "==> 部署完成 ✅"
echo "    健康检查: curl http://35.201.186.56:7777/health"
echo "    版本查询: curl http://35.201.186.56:7777/version"
