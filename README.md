# Lark 机器人 + GCP 云服务器 + 事件订阅

本地项目与 Google Cloud 上一台 VM 连通，实现：**飞书事件订阅 → 消息发到云服务器 → 你在这里写的代码逻辑处理并回复**。

## 架构概览

```
飞书用户发消息 → 飞书开放平台 → HTTP POST 到你 VM 的 /event
                                    ↓
                            app.py 处理事件并调用发消息 API
                                    ↓
                            飞书里用户收到机器人回复
```

## 一、在 Google Cloud 上新建 VM

1. 安装并登录 [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)：
   ```bash
   gcloud init
   gcloud auth login
   ```

2. 修改并执行创建脚本（或设置环境变量后执行）：
   ```bash
   cd /Users/lynn/lark-bot-gcp
   chmod +x scripts/create_gcp_vm.sh
   export GCP_PROJECT_ID=你的项目ID
   ./scripts/create_gcp_vm.sh
   ```

3. 获取 VM 公网 IP：
   ```bash
   gcloud compute instances describe lark-bot-server --zone=asia-east1-b --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
   ```
   记下该 IP，后面飞书「请求地址」填：`http://<该IP>:7777/event`（若改用 80 端口则用 `http://<该IP>/event`）。

## 二、在飞书开发者后台配置事件订阅

1. 打开 [飞书开放平台](https://open.feishu.cn/app)，进入你已创建的**企业自建应用**。

2. **事件与回调** → **事件订阅**：
   - 选择「**将事件发送至开发者服务器**」。
   - **请求地址**填：`http://<你的VM公网IP>:7777/event`（必须公网可访问，且飞书能访问；若需 HTTPS 可再在 VM 上配 nginx + 证书）。
   - 若配置了**加密**：在「加密配置」中设置 Encrypt Key、Verification Token，并在本项目的 `.env` 里填写 `LARK_ENCRYPT_KEY`、`LARK_VERIFICATION_TOKEN`。

3. **添加事件**：
   - 添加「**接收消息**」类事件（v2.0：`im.message.receive_v1`），保存并发布应用版本。

4. **权限**：
   - 在「权限管理」中开通「获取与发送单聊、群组消息」或「以应用的身份发消息」等发消息所需权限，并发布版本。

5. **可用范围**：
   - 将需要收到机器人回复的用户/群组加入可用范围。

## 三、把项目和 VM 连通（可更新部署）

1. 在 VM 上准备好目录（首次可 SSH 上去执行）：
   ```bash
   ssh 你的用户名@<VM_IP> "mkdir -p ~/lark-bot-gcp"
   ```

2. 在 VM 上配置环境变量（首次必须）：
   ```bash
   scp .env.example 你的用户名@<VM_IP>:~/lark-bot-gcp/.env
   ssh 你的用户名@<VM_IP> "nano ~/lark-bot-gcp/.env"
   ```
   在 `.env` 中填入：`LARK_APP_ID`、`LARK_APP_SECRET`，以及若启用加密时的 `LARK_ENCRYPT_KEY`、`LARK_VERIFICATION_TOKEN`。

3. 本地一键部署/更新代码到 VM：
   ```bash
   export VM_HOST=<VM公网IP>
   export VM_USER=你的SSH用户名  # GCP 常见为本地用户名，或查看实例详情
   ./scripts/deploy.sh
   ```
   之后每次改完 `app.py` 或其它代码，再执行一次 `./scripts/deploy.sh` 即可更新云上服务。

## 四、在本地编写回复逻辑

业务逻辑在 **`app.py`** 的 `handle_im_message` 中：

- 从 `data.event.message` 取 `chat_id`、`message_id`、`content`（文本消息为 `{"text":"..."}`）。
- 根据内容编写回复文案或调用其它 API，然后调用 `reply_text(...)` 向同一 `chat_id` 发消息。

飞书要求** 3 秒内**对事件请求返回 HTTP 200，若逻辑较重，建议先快速返回 200，再在后台异步发回复。

## 五、本地调试（可选）

```bash
cd /Users/lynn/lark-bot-gcp
cp .env.example .env   # 填入 APP_ID、APP_SECRET 等
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python app.py
```

本地运行时飞书无法直接访问，可用内网穿透（如 ngrok）将 `http://localhost:7777/event` 暴露为公网 URL，在飞书后台先填该 URL 做联调。

## 六、文件说明

| 文件/目录 | 说明 |
|-----------|------|
| `app.py` | 事件接收与回复逻辑入口，在此改机器人行为 |
| `requirements.txt` | Python 依赖（lark-oapi、flask、python-dotenv） |
| `.env.example` | 环境变量模板，复制为 `.env` 并填写 |
| `scripts/create_gcp_vm.sh` | 创建 GCP VM 与防火墙 |
| `scripts/deploy.sh` | 将本项目同步到 VM 并重启服务 |
| `scripts/setup_vm_first_time.sh` | VM 首次环境安装说明 |

完成以上步骤后，在飞书中对机器人或所在群发消息，即可在云上收到事件并用你编写的逻辑回复。
