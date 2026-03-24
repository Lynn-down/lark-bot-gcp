"""
Lark HR 小机器人 - v5.3
使用飞书SDK正确解析事件 + 新版合同生成（真实DOCX模板）
"""
APP_VERSION = "v5.3-real-docx-contract"

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
from lark_oapi.adapter.flask import parse_req, parse_resp

# 导入功能模块
from contract_generator import (
    generate_contract,
    detect_contract_type,
    extract_fields_via_llm,
    CONTRACT_TYPE_NAMES,
)
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
HR_USER_IDS = ["946d1fc5", "triplet"]

# 飞书配置
ENCRYPT_KEY = os.environ.get("LARK_ENCRYPT_KEY", "")
VERIFICATION_TOKEN = os.environ.get("LARK_VERIFICATION_TOKEN", "")
APP_ID = os.environ.get("LARK_APP_ID", "")
APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
OPEN_API_BASE = "https://open.feishu.cn/open-apis"

# 初始化名册
init_roster()

# 消息去重
_MAX_PROCESSED = 5000
_processed_ids: set = set()
_processed_lock = threading.Lock()

# 飞书 access token 缓存
_token_cache: Dict[str, Any] = {"token": "", "expires_at": 0}

def get_access_token() -> str:
    """获取 tenant_access_token（带缓存，有效期内复用）"""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    try:
        resp = requests.post(
            f"{OPEN_API_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": APP_ID, "app_secret": APP_SECRET},
            timeout=10
        )
        data = resp.json()
        if data.get("code") == 0:
            _token_cache["token"] = data["tenant_access_token"]
            _token_cache["expires_at"] = now + data.get("expire", 7200)
            logger.info("Access token refreshed")
            return _token_cache["token"]
        else:
            logger.error(f"Token fetch failed: {data}")
    except Exception as e:
        logger.error(f"Token fetch error: {e}")
    return ""


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
    """添加表情回应"""
    try:
        token = get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        r = requests.post(
            f"{OPEN_API_BASE}/im/v1/messages/{message_id}/reactions",
            headers=headers,
            json={"reaction_type": {"emoji_type": emoji_type}},
            timeout=10,
        )
        return r.status_code < 300
    except Exception as e:
        logger.warning(f"add_reaction failed: {e}")
        return False


def reply_text(chat_id: str, text: str) -> bool:
    """发送文本消息"""
    try:
        headers = {
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type": "application/json"
        }
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
        if resp.status_code == 200:
            logger.info(f"Message sent to {chat_id}")
            return True
        else:
            logger.error(f"Send failed: {resp.status_code} {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Send exception: {e}")
        return False


def get_onboarding_info(is_hr: bool) -> str:
    """入职信息查询"""
    if is_hr:
        return """【HR入职管理指南】📋

入职前准备：
1. 确认offer信息
2. 准备劳动合同/劳务合同
3. 开通飞书账号和邮箱
4. 安排工位和设备

入职当天：
1. 上午10点接待
2. 签署合同
3. 配置环境
4. 团队介绍

注意：实习生签劳务合同，全职签劳动合同"""
    else:
        return """【新员工入职指南】🎉

入职准备：
请携带：身份证、学历证明、离职证明、一寸照片2张、银行卡

入职当天：
📍 东升大厦A座4楼
⏰ 上午10点
👤 联系人：陆俊豪

当天流程：
1. 前台联系陆俊豪
2. 签署劳动合同
3. 配置飞书账号
4. 领取入职礼包
5. 熟悉环境

有问题随时问HR！😊"""


# ============ 工具定义 ============

def tool_query_member(keyword: str) -> str:
    return query_member(keyword)

def tool_get_roster_stats() -> str:
    return get_roster_stats()

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_member",
            "description": "Query member info",
            "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_roster_stats",
            "description": "Get personnel statistics",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

AVAILABLE_FUNCTIONS = {
    "query_member": tool_query_member,
    "get_roster_stats": tool_get_roster_stats
}


# ============ 核心处理逻辑 ============

def process_message(user_message: str, user_id: str, sender_name: str) -> str:
    """处理用户消息"""
    logger.info(f"[{user_id}/{sender_name}] Processing: {user_message[:50]}")
    
    # 特殊命令
    if user_message.lower() in ["/clear", "清空", "忘记"]:
        llm_client_v2.conversation_manager.clear_history(user_id)
        return "好的，之前的对话我都忘啦🙃"
    
    is_hr = is_hr_user(sender_name, user_id)
    
    # 合同生成（仅HR）
    if any(kw in user_message for kw in ["合同", "劳动合同", "劳务合同", "实习合同"]):
        if not is_hr:
            return "合同生成功能仅限HR使用哦～"
        return handle_contract(user_message)
    
    # 入职查询
    if any(kw in user_message for kw in ["入职", "新员工", "报到"]):
        return get_onboarding_info(is_hr)
    
    # 名册查询（直接处理，不经过LLM）
    if any(kw in user_message for kw in ["是谁", "的资料", "的信息", "职位", "岗位", "部门", "联系方式", "邮箱", "电话"]):
        names = re.findall(r'[\u4e00-\u9fa5]{2,4}', user_message)
        if names:
            return query_member(names[0])
    
    if any(kw in user_message for kw in ["多少", "几个", "人数", "统计"]):
        return get_roster_stats()
    
    # 其他使用LLM
    try:
        return llm_client_v2.chat_with_tools(
            user_message=user_message,
            user_id=user_id,
            tools=TOOLS,
            available_functions=AVAILABLE_FUNCTIONS
        )
    except Exception as e:
        logger.error(f"LLM error: {e}")
        return "我现在有点忙，请稍后再试～"


def handle_contract(user_message: str) -> str:
    """
    处理合同生成请求。
    1. 识别合同类型（劳动/劳务/实习）
    2. 用 LLM 提取字段（支持自然语言描述）
    3. 校验必填字段，缺失时提示补充
    4. 后台生成 DOCX 并发送邮件
    """
    # ── 识别合同类型 ──
    contract_type = detect_contract_type(user_message)
    cn_name = CONTRACT_TYPE_NAMES[contract_type]

    # ── LLM 提取字段 ──
    try:
        _, fields = extract_fields_via_llm(user_message, llm_client_v2)
    except Exception as e:
        logger.error(f"Field extraction failed: {e}")
        fields = {}

    # ── 必填字段校验 ──
    required = {"name": "姓名", "job_title": "岗位名称", "salary": "薪资"}
    missing = [cn for k, cn in required.items()
               if not fields.get(k) or fields[k] in ("", "XXX")]
    if missing:
        return (f"收到你要生成「{cn_name}」的需求 ✅\n"
                f"还缺少以下信息，补充后我马上生成：\n"
                + "\n".join(f"  • {m}" for m in missing))

    name = fields["name"]

    # ── 后台生成 + 发送邮件 ──
    def _background():
        try:
            # 默认填补常用字段
            fields.setdefault("sign_date",
                              datetime.now().strftime("%Y-%m-%d"))
            fields.setdefault("work_location", "北京市")
            if contract_type == "labor":
                fields.setdefault("duration", "3")
                fields.setdefault("duration_unit", "年")
                fields.setdefault("probation_period", "3")
            else:
                fields.setdefault("duration_unit", "月")

            path = generate_contract(contract_type, fields, output_name=name)
            send_contract_email(DEFAULT_HR_EMAIL, path, name, cn_name)
            logger.info(f"Contract sent: {path}")
        except Exception as e:
            logger.error(f"Contract generation/send error: {e}", exc_info=True)

    threading.Thread(target=_background, daemon=True).start()
    return (f"收到！正在为「{name}」生成{cn_name} 📄\n"
            f"使用真实模板，格式与纸质版完全一致。\n"
            f"稍后发送至 {DEFAULT_HR_EMAIL} ✉️")


# ============ 飞书事件处理 ============

def handle_im_message(data) -> None:
    """处理飞书消息事件"""
    try:
        event = data.event
        message = event.message
        sender = event.sender.sender_id

        msg_id = message.message_id
        chat_id = message.chat_id
        user_id = sender.user_id
        sender_name = getattr(event.sender, 'name', '') or ""
        
        # 解析消息内容
        try:
            body = json.loads(message.content) if message.content else {}
            text = body.get("text", "").strip()
            # 移除@机器人
            text = re.sub(r'@\s*\w+\s*', '', text).strip()
        except:
            text = ""
        
        if not text:
            logger.info("Empty message")
            return
        
        logger.info(f"Message from {sender_name}({user_id}): {text[:50]}")
        
        # 去重
        with _processed_lock:
            if msg_id in _processed_ids:
                return
            _processed_ids.add(msg_id)
            if len(_processed_ids) > _MAX_PROCESSED:
                _processed_ids.clear()
        
        # 添加反应（静默失败，不影响主流程）
        try:
            add_reaction(msg_id, "STRIVE")
        except Exception:
            pass
        
        # 处理并回复
        reply = process_message(text, user_id, sender_name)
        logger.info(f"Reply: {reply[:100]}")
        
        success = reply_text(chat_id, reply)
        if not success:
            logger.error("Failed to send reply")
    
    except Exception as e:
        logger.exception(f"Handle message error: {e}")


def handle_reaction_event(data) -> None:
    """忽略表情回应事件（避免 SDK 报 processor not found）"""
    pass


# 飞书事件处理器
handler = lark.EventDispatcherHandler.builder(ENCRYPT_KEY, VERIFICATION_TOKEN, lark.LogLevel.INFO) \
    .register_p2_im_message_receive_v1(handle_im_message) \
    .register_p2_im_message_reaction_created_v1(handle_reaction_event) \
    .build()


@app.route("/event", methods=["POST"])
def event():
    """飞书事件入口"""
    resp = handler.do(parse_req())
    return parse_resp(resp)


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "version": APP_VERSION}


@app.route("/version", methods=["GET"])
def version():
    return {
        "version": APP_VERSION,
        "model": os.environ.get("LLM_MODEL", "unknown"),
        "features": ["claude-sonnet", "conversation-memory"]
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7777))
    app.run(host="0.0.0.0", port=port)
