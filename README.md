# Lark HR 小机器人 v3.0 - LLM智能驱动

基于飞书开放平台和 LLM 的 HR 智能助手，支持公司信息查询、文档阅读、智能问答等功能。

## 🆕 v3.0 新特性

- **LLM智能架构**：输入 → LLM意图识别 → 调用工具 → LLM润色 → 输出回复
- **公司信息智能管理**：支持查询和更新公司信息、部门、制度、FAQ等
- **智能意图识别**：自动理解用户意图，无需记忆固定指令
- **自然语言回复**：LLM润色后的友好、专业回复

## 📐 架构概览

```
用户消息 → 飞书开放平台 → /event
                    ↓
            LLM 意图识别
                    ↓
            工具调用（查询/更新/阅读）
                    ↓
            LLM 润色回复
                    ↓
            飞书用户收到回复
```

## 🚀 快速开始

### 1. 环境配置

```bash
cd /Users/lynn/lark-bot-gcp
cp .env.example .env
```

编辑 `.env` 文件，填入以下配置：

```bash
# 飞书应用凭证（飞书开发者后台 → 凭证与基础信息）
LARK_APP_ID=your_app_id
LARK_APP_SECRET=your_app_secret

# 事件订阅加密配置（可选）
LARK_ENCRYPT_KEY=
LARK_VERIFICATION_TOKEN=

# 服务端口
PORT=7777

# LLM API 配置（已内置，如需更换请修改）
LLM_API_URL=https://api.ablai.top/token
LLM_API_KEY=your_api_key
LLM_MODEL=gpt-4o-mini
```

### 2. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 本地测试

```bash
python app.py
```

使用 ngrok 暴露本地服务用于飞书调试：

```bash
ngrok http 7777
```

将 ngrok 提供的 https URL + `/event` 填入飞书事件订阅配置。

### 4. 部署到 GCP

```bash
# 设置环境变量
export VM_HOST=your_vm_ip
export VM_USER=your_ssh_username

# 执行部署脚本
./scripts/deploy.sh
```

## 💬 功能列表

### 公司信息查询

| 功能 | 示例指令 |
|------|----------|
| 查询公司介绍 | "介绍一下我们公司" |
| 查询部门信息 | "有哪些部门？" "技术部是做什么的？" |
| 查询规章制度 | "考勤制度是什么？" "请假流程" |
| 查询FAQ | "WiFi密码是多少？" "打印机怎么用？" |
| 查询公告 | "最近有什么公告？" |

### 公司信息更新（需要权限）

管理员可以通过特定格式更新公司信息：

```
添加FAQ：
问题：如何申请加班？
答案：请在OA系统提交加班申请
```

```
添加公告：
标题：年会通知
内容：公司年会将于12月30日举行
```

### 文档阅读

- 发送文档链接并说"读一下"
- 支持 docx、doc、sheets 等飞书文档格式

### 日常问答

- 问候："你好" "早上好"
- 询问功能："你能做什么" "有什么功能"

## 📁 文件说明

| 文件 | 说明 |
|------|------|
| `app.py` | 主程序，包含LLM架构实现 |
| `company_info.json` | 公司信息数据文件 |
| `requirements.txt` | Python依赖 |
| `.env.example` | 环境变量模板 |
| `docs/` | 文档目录 |

## 🔧 配置公司信息

编辑 `company_info.json` 文件来自定义公司信息：

```json
{
  "company": {
    "name": "你的公司名",
    "description": "公司简介",
    "address": "公司地址",
    "contact": {
      "phone": "400-xxx-xxxx",
      "email": "contact@company.com"
    }
  },
  "departments": [...],
  "policies": [...],
  "faqs": [...],
  "announcements": [...]
}
```

## 🛠️ 技术栈

- **后端**：Flask + Python 3
- **飞书 SDK**：lark-oapi
- **LLM API**：OpenAI Compatible API
- **部署**：Google Cloud Platform

## 📡 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/event` | POST | 飞书事件订阅入口 |
| `/health` | GET | 健康检查 |
| `/version` | GET | 获取版本信息 |
| `/company_info` | GET | 获取公司信息（参数：type, keyword） |

## 🔒 安全说明

- 请勿将 `.env` 文件提交到 Git
- API Key 等敏感信息通过环境变量注入
- 生产环境建议使用 HTTPS

## 📝 更新日志

### v3.0 (2024-12)
- ✨ 全新 LLM 驱动架构
- ✨ 公司信息查询和更新功能
- ✨ 智能意图识别
- ✨ LLM 润色回复

### v2.0
- 文档阅读功能（docx/sheets/wiki）
- 技能内化功能

### v1.0
- 基础消息回复
- 飞书事件订阅

---

有问题或建议？欢迎提交 Issue 或 PR！
