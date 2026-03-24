#!/usr/bin/env bash
# 在 GCP VM 上首次运行：安装 Python3、创建目录、拉取或接收代码后安装依赖并配置运行。
# 用法：可复制到 VM 上执行，或通过 ssh 一行执行：
#   curl -sL https://...  | bash
#  或：在本地执行 deploy.sh 后，再 ssh 到 VM 执行下面「在 VM 上」部分。

# ---------- 在 VM 上执行 ----------
# 以下假设已 ssh 到 VM，且项目已在 /home/$USER/lark-bot-gcp

# 安装 Python 与 venv（Debian/Ubuntu）
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv

# 进入项目目录（若用 deploy.sh 同步，目录已存在）
cd ~/lark-bot-gcp || exit 1

# 创建虚拟环境并安装依赖
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# 复制环境变量并编辑（必填：LARK_APP_ID, LARK_APP_SECRET；若开启加密则填 ENCRYPT_KEY, VERIFICATION_TOKEN）
cp .env.example .env
echo "请编辑 .env 填入飞书应用凭证: nano .env"

# 前台测试运行（Ctrl+C 退出）
# PORT=80 python app.py   # 若用 80 端口需 sudo 或 capability

# 后台运行（可选）
# nohup .venv/bin/python app.py >> app.log 2>&1 &
