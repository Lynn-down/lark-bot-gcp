"""
Lark HR 小机器人 - v5.1 完整版
- Claude Sonnet 4.5
- 对话历史记忆
- Function Calling
- 区分HR/普通用户权限
- 入职查询分权限显示
"""
APP_VERSION = "v5.1-claude-sonnet"

import os
import re
import json
import time
import logging
import threading
from typing import Dict, List, Optional, Any
from flask import Flask, request
from datetime import datetime

import requests
import lark_oapi as lark
from lark_oapi.api.im.v1 import *

# 导入功能模块
from contract_v2 import smart_extract_info, generate_labor_contract_v2
from roster_module import query_member, get_roster_stats, init_roster
from email_sender import send_contract_email
from llm_client_v2 import llm_client_v2

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 配置
DEFAULT_HR_EMAIL = "jyx@group-ultra.com"
HR_USERS = ["蒋雨萱", "丁怡菲", "刘怡馨", "triplet", "戴祥和", "陈春宇"]
HR_USER_IDS = ["946d1fc5", "triplet"]  # 用户ID

# 飞书配置
ENCRYPT_KEY = os.environ.get("LARK_ENCRYPT_KEY", "")
VERIFICATION_TOKEN = os.environ.get("LARK_VERIFICATION_TOKEN", "")
APP_ID = os.environ.get("LARK_APP_ID", "")
APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
OPEN_API_BASE = "https://open.feishu.cn/open-apis"

# Token缓存
_token_cache = {"token": "", "expires_at": 0.0}

# 消息去重
_MAX_PROCESSED = 5000
_processed_ids: set = set()
_processed_lock = threading.Lock()

# 初始化名册
init_roster()


def _get_tenant_access_token() -> str:
    """获取tenant_access_token"""
    global _token_cache
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 300:
        return _token_cache["token"]
    
    if not APP_ID or not APP_SECRET:
        raise RuntimeError("Missing LARK_APP_ID / LARK_APP_SECRET")
    
    r = requests.post(
        f"{OPEN_API_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=10,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"token failed: {data.get('msg')}")
    
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires_at"] = time.time() + float(data.get("expire", 7200))
    return _token_cache["token"]


def _open_api_headers() -> Dict[str, str]:
    """获取API请求头"""
    return {
        "Authorization": f"Bearer {_get_tenant_access_token()}",
        "Content-Type": "application/json"
    }


def is_hr_user(sender_name: str, sender_id: str = "") -> bool:
    """判断用户是否是HR"""
    if sender_name:
        for hr in HR_USERS:
            if hr in sender_name or sender_name in hr:
                return True
    if sender_id:
        for hr_id in HR_USER_IDS:
            if hr_id in sender_id or sender_id in hr_id:
                return True
    return False


def add_reaction(message_id: str, emoji_type: str = "STRIVE") -> bool:
    """给消息添加表情回应"""
    try:
        r = requests.post(
            f"{OPEN_API_BASE}/im/v1/messages/{message_id}/reactions",
            headers=_open_api_headers(),
            json={"reaction_type": {"emoji_type": emoji_type}},
            timeout=10,
        )
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code >= 400 or data.get("code") not in (0, None):
            logger.warning(f"add_reaction failed: {r.status_code}, {data}")
            return False
        return True
    except Exception as e:
        logger.warning(f"add_reaction exception: {e}")
        return False


def reply_text(chat_id: str, text: str) -> bool:
    """发送文本消息"""
    try:
        # 使用requests直接调用API，更可靠
        headers = _open_api_headers()
        resp = requests.post(
            f"{OPEN_API_BASE}/im/v1/messages?receive_id_type=chat_id",
            headers=headers,
            json={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text})
            },
            timeout=10
        )
        data = resp.json()
        if data.get("code") == 0:
            logger.info(f"Message sent to {chat_id}")
            return True
        else:
            logger.error(f"Send message failed: {data}")
            return False
    except Exception as e:
        logger.error(f"Send message exception: {e}")
        return False


def get_onboarding_info(is_hr: bool) -> str:
    """获取入职信息，区分HR和普通用户"""
    if is_hr:
        return """【HR入职管理指南】📋

**入职前准备：**
1. 确认新员工offer信息
2. 准备劳动合同/劳务合同
3. 开通飞书账号和邮箱
4. 安排工位和电脑设备
5. 准备入职资料包

**入职当天流程：**
1. 上午10点到公司接待
2. 签署劳动合同
3. 配置VPN和开发环境
4. 介绍团队成员
5. 分配第一个任务

**注意事项：**
- 实习生需签劳务合同，非劳动合同
- 全职员工需办理五险一金
- 外籍员工需准备工作许可相关文件"""
    else:
        return """【新员工入职指南】🎉

**入职前准备：**
请携带以下材料：
- 身份证原件及复印件
- 学历证明
- 离职证明（如有）
- 一寸照片2张
- 银行卡（工资卡）

**入职当天：**
📍 地点：东升大厦A座4楼
⏰ 时间：上午10点
👤 联系人：陆俊豪（HR）

**当天流程：**
1. 到前台联系陆俊豪接待
2. 签署劳动合同
3. 配置飞书账号和邮箱
4. 领取入职礼包
5. 熟悉办公环境

**办公环境：**
- WiFi: Ultra-Guest / 密码见入职邮件
- 工位：开放式办公，找HR安排
- 会议室：需要提前在飞书预约

有问题随时问HR小伙伴！😊"""


def get_company_info(query_type: str, keyword: str = "") -> str:
    """查询公司信息"""
    try:
        with open("company_info.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if query_type == "company" or keyword in ["公司", "介绍"]:
            company = data.get("company", {})
            return f"""【{company.get('name', '极群科技')}】

📍 地址：{company.get('address', '东升大厦A座4楼')}
📧 邮箱：{company.get('email', 'hr@group-ultra.com')}
🌐 官网：{company.get('website', 'www.group-ultra.com')}

{company.get('description', '极群科技是一家专注于AI和社交产品的科技公司。')}"""
        
        elif query_type == "department" or keyword in ["部门", "团队"]:
            depts = data.get("departments", [])
            lines = ["【公司部门】"]
            for d in depts:
                lines.append(f"• {d.get('name', 'N/A')}: {d.get('description', '')[:30]}...")
            return "\n".join(lines)
        
        elif query_type == "policy" or keyword in ["制度", "规定"]:
            policies = data.get("policies", [])
            lines = ["【公司制度】"]
            for p in policies[:5]:
                lines.append(f"• {p.get('title', 'N/A')}")
            return "\n".join(lines)
        
        elif query_type == "faq" or keyword in ["wifi", "密码", "wifi密码"]:
            faqs = data.get("faqs", [])
            for f in faqs:
                if keyword.lower() in f.get("question", "").lower():
                    return f"【{f.get('question')}】\n{f.get('answer')}"
            return "没找到相关FAQ，可以问问陆俊豪～"
        
        else:
            return """可以查询：
- 公司介绍
- 部门信息
- 入职指南
- 规章制度
- WiFi密码"""
    
    except Exception as e:
        logger.error(f"get_company_info error: {e}")
        return f"查询出错，直接问HR吧～"


# ============ 工具函数定义 ============

def tool_query_member_wrapper(keyword: str) -> str:
    """查询成员信息"""
    return query_member(keyword)

def tool_get_roster_stats_wrapper() -> str:
    """获取人员统计"""
    return get_roster_stats()

def tool_query_company_info_wrapper(query_type: str = "all", keyword: str = "") -> str:
    """查询公司信息"""
    return get_company_info(query_type, keyword)

def tool_get_current_time_wrapper() -> str:
    """获取当前时间"""
    return datetime.now().strftime("%Y年%m月%d日 %H:%M")


# ============ Function Calling 工具定义 ============

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_member",
            "description": "查询成员信息，支持姓名、职位模糊搜索",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "姓名或职位关键词"}
                },
                "required": ["keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_roster_stats",
            "description": "获取人员统计数据，如总人数、在职人数、实习生数量等",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_company_info",
            "description": "查询公司信息，包括部门、规章制度、入职指南等",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {"type": "string", "enum": ["company", "department", "policy", "onboarding", "faq", "all"]},
                    "keyword": {"type": "string"}
                },
                "required": ["query_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前时间",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

AVAILABLE_FUNCTIONS = {
    "query_member": tool_query_member_wrapper,
    "get_roster_stats": tool_get_roster_stats_wrapper,
    "query_company_info": tool_query_company_info_wrapper,
    "get_current_time": tool_get_current_time_wrapper
}


# ============ 核心处理逻辑 ============

def process_message(user_message: str, user_id: str, sender_name: str) -> str:
    """处理用户消息"""
    logger.info(f"[{user_id}/{sender_name}] Processing: {user_message[:50]}")
    
    # 特殊命令
    if user_message.lower() in ["/clear", "清空", "忘记"]:
        llm_client_v2.conversation_manager.clear_history(user_id)
        return "好的，之前的对话我都忘啦🙃 有什么新问题吗？"
    
    # 判断是否是HR
    is_hr = is_hr_user(sender_name, user_id)
    logger.info(f"User {sender_name} is_hr={is_hr}")
    
    # 合同生成（仅HR）
    contract_keywords = ["生成合同", "劳动合同", "劳务合同", "做合同"]
    if any(kw in user_message for kw in contract_keywords):
        if not is_hr:
            return "合同生成功能仅限HR使用哦～"
        return handle_contract_generation(user_message)
    
    # 入职查询（区分HR/普通用户）
    onboarding_keywords = ["入职", "新员工", "报到", "入职流程", "入职准备"]
    if any(kw in user_message for kw in onboarding_keywords):
        return get_onboarding_info(is_hr)
    
    # 其他查询使用LLM + 工具
    try:
        response = llm_client_v2.chat_with_tools(
            user_message=user_message,
            user_id=user_id,
            tools=TOOLS,
            available_functions=AVAILABLE_FUNCTIONS
        )
        return response
    except Exception as e:
        logger.error(f"Process error: {e}")
        return "哎呀，我卡住了🤯 你能再说一遍吗？"


def handle_contract_generation(user_message: str) -> str:
    """处理合同生成"""
    contract_data = smart_extract_info(user_message)
    
    required = ["员工姓名", "岗位名称", "税前工资"]
    missing = [f for f in required if not contract_data.get(f) or contract_data.get(f) == "XXX"]
    
    if missing:
        field_names = {"员工姓名": "员工姓名", "岗位名称": "岗位名称", "税前工资": "税前工资（月薪）"}
        missing_text = "、".join([field_names.get(f, f) for f in missing])
        return f"请补充以下信息：{missing_text}"
    
    employee_name = contract_data["员工姓名"]
    
    import threading
    def generate_and_send():
        try:
            docx_path = generate_labor_contract_v2(contract_data)
            send_contract_email(
                to_email=DEFAULT_HR_EMAIL,
                contract_path=docx_path,
                employee_name=employee_name,
                contract_type="劳动合同"
            )
        except Exception as e:
            logger.error(f"Contract generation failed: {e}")
    
    threading.Thread(target=generate_and_send).start()
    return f"收到！{employee_name}的劳动合同正在制作中，稍后发送到 {DEFAULT_HR_EMAIL} 📧"


# ============ 飞书事件处理 ============

@app.route("/event", methods=["POST"])
def handle_event():
    """处理飞书事件"""
    try:
        data = request.get_json() or {}
        logger.debug(f"Received event: {json.dumps(data, ensure_ascii=False)[:500]}")
        
        # URL验证
        if data.get("type") == "url_verification":
            challenge = data.get("challenge", "")
            logger.info(f"URL verification: {challenge}")
            return json.dumps({"challenge": challenge})
        
        # 处理消息事件
        event = data.get("event", {})
        if not event:
            logger.warning("No event in data")
            return "", 200
        
        message = event.get("message", {})
        if message.get("message_type") != "text":
            logger.info(f"Non-text message: {message.get('message_type')}")
            return "", 200
        
        # 提取消息信息
        msg_id = message.get("message_id", "")
        chat_id = message.get("chat_id", "")
        content = message.get("content", "{}")
        
        sender = event.get("sender", {}).get("sender_id", {})
        user_id = sender.get("user_id", "unknown")
        sender_name = sender.get("name", "")
        
        logger.info(f"Message from {sender_name}({user_id}) in chat {chat_id}")
        
        # 解析消息文本
        try:
            body = json.loads(content) if isinstance(content, str) else {}
            text = body.get("text", "").strip()
            # 移除@机器人的部分
            text = re.sub(r'@ ?\w+\s*', '', text).strip()
        except Exception as e:
            logger.error(f"Parse content error: {e}")
            text = ""
        
        if not text:
            logger.info("Empty text after parsing")
            return "", 200
        
        logger.info(f"Parsed text: {text[:100]}")
        
        # 去重
        with _processed_lock:
            if msg_id in _processed_ids:
                logger.info(f"Duplicate message: {msg_id}")
                return "", 200
            _processed_ids.add(msg_id)
            if len(_processed_ids) > _MAX_PROCESSED:
                _processed_ids.clear()
        
        # 添加表情反应
        add_reaction(msg_id, "STRIVE")
        
        # 处理消息
        reply = process_message(text, user_id, sender_name)
        logger.info(f"Reply: {reply[:100]}")
        
        # 发送回复
        success = reply_text(chat_id, reply)
        if not success:
            logger.error("Failed to send reply")
        
        return "", 200
    
    except Exception as e:
        logger.exception(f"Handle event error: {e}")
        return "", 500


@app.route("/health", methods=["GET"])
def health_check():
    return json.dumps({"status": "ok", "version": APP_VERSION})


@app.route("/version", methods=["GET"])
def version():
    return json.dumps({
        "version": APP_VERSION,
        "model": os.environ.get("LLM_MODEL", "unknown"),
        "features": ["claude-sonnet", "conversation-memory", "function-calling", "hr-permissions"]
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7777))
    app.run(host="0.0.0.0", port=port)
