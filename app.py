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

# 导入功能模块
from contract_v2 import smart_extract_info, generate_labor_contract_v2
from roster_module import query_member, get_roster_stats, init_roster
from email_sender import send_contract_email
from llm_client_v2 import llm_client_v2  # 新的LLM客户端

from lark_oapi.adapter.flask import *
from lark_oapi.api.im.v1 import *

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 配置
DEFAULT_HR_EMAIL = "jyx@group-ultra.com"
HR_USERS = ["蒋雨萱", "丁怡菲", "刘怡馨", "triplet", "戴祥和", "陈春宇"]

# 初始化名册
init_roster()

# 消息去重
_MAX_PROCESSED = 5000
_processed_ids: set = set()
_processed_lock = threading.Lock()

def is_hr_user(sender_name, sender_id=""):
    """判断用户是否是HR"""
    if not sender_name:
        return sender_id and any(hr in sender_id for hr in ["946d1fc5", "triplet"])
    return any(hr_name in sender_name for hr_name in HR_USERS)


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
            return f"【{company.get('name', '极群科技')}】\n地址：{company.get('address', 'N/A')}\n邮箱：{company.get('email', 'N/A')}\n官网：{company.get('website', 'N/A')}"
        
        elif query_type == "department":
            depts = data.get("departments", [])
            if keyword:
                for d in depts:
                    if keyword in d.get("name", ""):
                        return f"【{d.get('name')}】\n{d.get('description', 'N/A')}"
            return "部门列表：\n" + "\n".join([f"- {d.get('name')}: {d.get('description', 'N/A')[:50]}..." for d in depts[:5]])
        
        elif query_type == "policy":
            policies = data.get("policies", [])
            if keyword:
                for p in policies:
                    if keyword in p.get("title", ""):
                        return f"【{p.get('title')}】\n{p.get('content', 'N/A')}"
            return "规章制度：\n" + "\n".join([f"- {p.get('title')}" for p in policies[:5]])
        
        elif query_type == "onboarding":
            onboarding = data.get("onboarding", {})
            materials = onboarding.get("materials", [])
            return f"【入职准备】\n需要携带：\n" + "\n".join([f"- {m}" for m in materials[:5]])
        
        return "可以查询：公司信息、部门介绍、规章制度、入职指南等"
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
            "description": "查询成员信息，支持姓名、职位模糊搜索",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词，如姓名、职位等"
                    }
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
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_company_info",
            "description": "查询公司信息，包括公司介绍、部门、规章制度、入职指南等",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": ["company", "department", "policy", "onboarding", "all"],
                        "description": "查询类型"
                    },
                    "keyword": {
                        "type": "string",
                        "description": "关键词，用于精确筛选"
                    }
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
            "parameters": {
                "type": "object",
                "properties": {}
            }
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
    """
    处理用户消息 - 简化架构
    单次LLM调用 + Function Calling
    """
    logger.info(f"[{user_id}] Processing: {user_message[:50]}...")
    
    # 特殊命令处理
    if user_message.lower() in ["/clear", "清空", "忘记"]:
        llm_client_v2.conversation_manager.clear_history(user_id)
        return "好的，之前的对话我都忘啦🙃 有什么新问题吗？"
    
    # 合同生成（HR专用，保持原有逻辑）
    contract_keywords = ["合同", "生成合同", "劳动合同", "劳务合同"]
    if any(kw in user_message for kw in contract_keywords):
        if not is_hr_user(sender_name, user_id):
            return "合同生成功能仅限HR使用哦～"
        return handle_contract_generation(user_message)
    
    # 使用新的LLM客户端处理（带工具调用）
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
    """处理合同生成请求"""
    import re
    
    # 提取信息
    contract_data = smart_extract_info(user_message)
    
    # 检查必填字段
    required = ["员工姓名", "岗位名称", "税前工资"]
    missing = [f for f in required if not contract_data.get(f) or contract_data.get(f) == "XXX"]
    
    if missing:
        field_names = {"员工姓名": "员工姓名", "岗位名称": "岗位名称", "税前工资": "税前工资（月薪）"}
        missing_text = "、".join([field_names.get(f, f) for f in missing])
        return f"请补充以下信息以便生成合同：{missing_text}"
    
    employee_name = contract_data["员工姓名"]
    
    # 后台生成并发送
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
            logger.error(f"合同生成失败: {e}")
    
    threading.Thread(target=generate_and_send).start()
    return f"收到！{employee_name}的劳动合同正在制作中，稍后发送到 {DEFAULT_HR_EMAIL} 📧"


# ============ 飞书事件处理 ============

@app.route("/event", methods=["POST"])
def handle_event():
    """处理飞书事件"""
    # 简化的处理逻辑
    data = request.get_json() or {}
    
    # URL验证
    if data.get("type") == "url_verification":
        return json.dumps({"challenge": data.get("challenge")})
    
    # 处理消息事件
    event_data = data.get("event", {})
    msg_type = event_data.get("message", {}).get("message_type")
    
    if msg_type == "text":
        content = json.loads(event_data.get("message", {}).get("content", "{}"))
        text = content.get("text", "").strip()
        user_id = event_data.get("sender", {}).get("sender_id", {}).get("user_id", "unknown")
        sender_name = event_data.get("sender", {}).get("sender_id", {}).get("name", "")
        
        # 去重检查
        msg_id = event_data.get("message", {}).get("message_id", "")
        with _processed_lock:
            if msg_id in _processed_ids:
                return "", 200
            _processed_ids.add(msg_id)
            if len(_processed_ids) > _MAX_PROCESSED:
                _processed_ids.clear()
        
        # 处理消息
        reply = process_message(text, user_id, sender_name)
        
        # 发送回复（这里简化处理，实际应调用飞书API回复）
        logger.info(f"Reply to {user_id}: {reply[:100]}...")
        return "", 200
    
    return "", 200


@app.route("/health", methods=["GET"])
def health_check():
    """健康检查"""
    return json.dumps({"status": "ok", "version": APP_VERSION})


@app.route("/version", methods=["GET"])
def version():
    """版本信息"""
    return json.dumps({
        "version": APP_VERSION,
        "model": os.environ.get("LLM_MODEL", "unknown"),
        "features": ["claude-sonnet", "conversation-memory", "function-calling", "roster-query"]
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7777))
    app.run(host="0.0.0.0", port=port)
