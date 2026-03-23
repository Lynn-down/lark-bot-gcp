"""
Lark HR 小机器人 - v5.0 增强版
- Claude Sonnet 4.5
- 对话历史记忆
- Function Calling
- 人格化回复
"""
APP_VERSION = "v5.0-claude-sonnet"

import os
import re
import json
import time
import logging
import threading
from typing import Dict, List, Optional, Callable, Any
from urllib.parse import urlparse, parse_qs
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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 配置
DEFAULT_HR_EMAIL = "jyx@group-ultra.com"
HR_USERS = ["蒋雨萱", "丁怡菲", "刘怡馨", "triplet", "戴祥和", "陈春宇"]

# 飞书配置
ENCRYPT_KEY = os.environ.get("LARK_ENCRYPT_KEY", "")
VERIFICATION_TOKEN = os.environ.get("LARK_VERIFICATION_TOKEN", "")
APP_ID = os.environ.get("LARK_APP_ID", "")
APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
OPEN_API_BASE = "https://open.feishu.cn/open-apis"

# 初始化名册
init_roster()

# Token缓存
_token_cache = {"token": "", "expires_at": 0.0}

# 消息去重
_MAX_PROCESSED = 5000
_processed_ids: set = set()
_processed_lock = threading.Lock()


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


def is_hr_user(sender_name, sender_id=""):
    """判断用户是否是HR"""
    if not sender_name:
        return sender_id and any(hr in sender_id for hr in ["946d1fc5", "triplet"])
    return any(hr_name in sender_name for hr_name in HR_USERS)


def add_reaction(message_id: str, emoji_type: str = "STRIVE") -> None:
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
            logger.warning("add_reaction failed: status=%s", r.status_code)
    except Exception as e:
        logger.warning("add_reaction exception: %s", e)


def reply_text(chat_id: str, text: str) -> bool:
    """发送文本消息"""
    try:
        req = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(json.dumps({"text": text}))
                .build()
            ) \
            .build()
        
        client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()
        resp = client.im.v1.message.create(req)
        
        if resp.success():
            logger.info("Message sent to %s", chat_id)
            return True
        else:
            logger.error("Send message failed: %s", resp.raw.content)
            return False
    except Exception as e:
        logger.error("Send message exception: %s", e)
        return False


# ============ 工具函数定义 ============

def tool_query_member_wrapper(keyword: str) -> str:
    """查询成员信息"""
    return query_member(keyword)

def tool_get_roster_stats_wrapper() -> str:
    """获取人员统计"""
    return get_roster_stats()

def tool_query_company_info(query_type: str = "all", keyword: str = "") -> str:
    """查询公司信息"""
    try:
        with open("company_info.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if query_type == "company":
            company = data.get("company", {})
            return f"【{company.get('name', '极群科技')}】\n地址：{company.get('address', 'N/A')}\n邮箱：{company.get('email', 'N/A')}"
        elif query_type == "department":
            depts = data.get("departments", [])
            return "部门列表：\n" + "\n".join([f"- {d.get('name')}" for d in depts[:10]])
        elif query_type == "onboarding":
            materials = data.get("onboarding", {}).get("materials", [])
            return "入职准备：\n" + "\n".join([f"- {m}" for m in materials[:5]])
        return "可以查询：公司信息、部门、入职指南等"
    except Exception as e:
        return f"查询出错：{str(e)}"

def tool_get_current_time() -> str:
    """获取当前时间"""
    return datetime.now().strftime("%Y年%m月%d日 %H:%M")


# ============ Function Calling 工具定义 ============

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_member",
            "description": "Query member info by name or position",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Name or position keyword"}
                },
                "required": ["keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_roster_stats",
            "description": "Get personnel statistics like total count, active employees, interns etc.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_company_info",
            "description": "Query company info including departments, policies, onboarding guide",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {"type": "string", "enum": ["company", "department", "policy", "onboarding", "all"]},
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
            "description": "Get current time",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

AVAILABLE_FUNCTIONS = {
    "query_member": tool_query_member_wrapper,
    "get_roster_stats": tool_get_roster_stats_wrapper,
    "query_company_info": tool_query_company_info,
    "get_current_time": tool_get_current_time
}


# ============ 核心处理逻辑 ============

def process_message(user_message: str, user_id: str, sender_name: str = "") -> str:
    """处理用户消息"""
    logger.info(f"[{user_id}] Processing: {user_message[:50]}...")
    
    # 特殊命令
    if user_message.lower() in ["/clear", "清空", "忘记"]:
        llm_client_v2.conversation_manager.clear_history(user_id)
        return "好的，之前的对话我都忘啦🙃 有什么新问题吗？"
    
    # 合同生成
    contract_keywords = ["合同", "生成合同", "劳动合同", "劳务合同"]
    if any(kw in user_message for kw in contract_keywords):
        if not is_hr_user(sender_name, user_id):
            return "合同生成功能仅限HR使用哦～"
        return handle_contract_generation(user_message)
    
    # 使用LLM处理
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
    data = request.get_json() or {}
    
    # URL验证
    if data.get("type") == "url_verification":
        return json.dumps({"challenge": data.get("challenge")})
    
    # 解析事件
    event = data.get("event", {})
    message = event.get("message", {})
    
    if message.get("message_type") != "text":
        return "", 200
    
    # 提取信息
    msg_id = message.get("message_id", "")
    chat_id = message.get("chat_id", "")
    content = message.get("content", "{}")
    sender = event.get("sender", {}).get("sender_id", {})
    user_id = sender.get("user_id", "unknown")
    sender_name = sender.get("name", "")
    
    # 解析消息文本
    try:
        body = json.loads(content) if isinstance(content, str) else {}
        text = body.get("text", "").strip()
    except:
        text = ""
    
    if not text:
        return "", 200
    
    # 去重
    with _processed_lock:
        if msg_id in _processed_ids:
            return "", 200
        _processed_ids.add(msg_id)
        if len(_processed_ids) > _MAX_PROCESSED:
            _processed_ids.clear()
    
    logger.info(f"Message from {sender_name}({user_id}): {text[:50]}")
    
    # 添加反应
    add_reaction(msg_id, "STRIVE")
    
    # 处理并回复
    reply = process_message(text, user_id, sender_name)
    reply_text(chat_id, reply)
    
    return "", 200


@app.route("/health", methods=["GET"])
def health_check():
    return json.dumps({"status": "ok", "version": APP_VERSION})


@app.route("/version", methods=["GET"])
def version():
    return json.dumps({
        "version": APP_VERSION,
        "model": os.environ.get("LLM_MODEL", "unknown"),
        "features": ["claude-sonnet", "conversation-memory", "function-calling"]
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7777))
    app.run(host="0.0.0.0", port=port)
