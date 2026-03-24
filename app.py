"""
Lark HR 小机器人 - v5.4
"""
APP_VERSION = "v5.5-claude-opus"

import os
import re
import json
import time
import logging
import threading
from typing import Dict, List, Optional, Any
from flask import Flask, request
from datetime import datetime

# ⚠️ load_dotenv 必须在所有业务模块 import 之前，否则 API key 读不到
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import requests
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from lark_oapi.adapter.flask import parse_req, parse_resp

# 导入功能模块（load_dotenv 已执行，环境变量已就绪）
from contract_generator import (
    generate_contract,
    detect_contract_type,
    extract_fields_via_llm,
    CONTRACT_TYPE_NAMES,
)
from roster_module import query_member, get_roster_stats, query_roster_detail, update_member, init_roster
from email_sender import send_contract_email
from llm_client_v2 import llm_client_v2

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 配置
DEFAULT_HR_EMAIL = "jyx@group-ultra.com"
HR_USERS = ["蒋雨萱", "丁怡菲", "刘怡馨", "triplet", "戴祥和", "陈春宇"]
HR_USER_IDS = ["946d1fc5", "9ddfdb23", "9bbc73b9", "triplet"]  # 946d1fc5=陈春宇 9ddfdb23=丁怡菲 9bbc73b9=刘怡馨

# 待处理合同状态（多轮追问）user_id → {contract_type, fields, chat_id, msg_id}
_pending_contracts: Dict[str, Dict] = {}
_pending_lock = threading.Lock()

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


def _make_card(text: str) -> dict:
    """
    把文本包装成飞书卡片（lark_md 格式）。
    自动把 Markdown 表格转换为分组块格式（lark_md 不支持 | 表格）。
    """
    text = _convert_table_to_blocks(text)
    return {
        "config": {"wide_screen_mode": True},
        "elements": [
            {
                "tag": "div",
                "text": {"content": text, "tag": "lark_md"}
            }
        ]
    }


def _convert_table_to_blocks(text: str) -> str:
    """
    把 Markdown 表格（| col | col |）转换为飞书 lark_md 支持的分组块格式。
    表头行 + 分割行会被跳过，数据行格式化为：
      **分类** · 数量
      成员名单...
    """
    import re

    def strip_bold(s: str) -> str:
        return re.sub(r'\*{1,2}(.*?)\*{1,2}', r'\1', s).strip()

    lines = text.split('\n')
    result = []
    header_skipped = False
    in_table = False
    i = 0

    while i < len(lines):
        line = lines[i]
        is_table_row = bool(re.match(r'^\s*\|', line))
        is_separator = bool(re.match(r'^\s*\|[-:\s|]+\|\s*$', line))

        if is_separator:
            # 分割行：标记表头已处理，跳过
            header_skipped = True
            in_table = True
            i += 1
            continue

        if is_table_row:
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            cells = [c for c in cells if c]

            if not header_skipped:
                # 表头行，跳过
                i += 1
                continue

            in_table = True
            if len(cells) == 0:
                i += 1
                continue
            elif len(cells) == 1:
                result.append(f"**{strip_bold(cells[0])}**")
            elif len(cells) == 2:
                result.append(f"**{strip_bold(cells[0])}** · {strip_bold(cells[1])}")
            else:
                # col0=分类 col1=数量 col2+=成员
                category = strip_bold(cells[0])
                count = strip_bold(cells[1])
                members = strip_bold(cells[2]) if len(cells) > 2 else ''
                result.append(f"**{category}** · {count}")
                if members:
                    result.append(f"  {members}")
            i += 1
            continue

        # 非表格行
        if in_table and not is_table_row:
            in_table = False
            header_skipped = False
        result.append(line)
        i += 1

    return '\n'.join(result)


def reply_text(chat_id: str, text: str) -> bool:
    """发送卡片消息（lark_md，支持 Markdown 表格/加粗/分割线）"""
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
                "msg_type": "interactive",
                "content": json.dumps(_make_card(text), ensure_ascii=False)
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


def reply_to_message(parent_msg_id: str, text: str) -> bool:
    """引用回复某条消息（卡片格式）"""
    try:
        headers = {
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type": "application/json"
        }
        resp = requests.post(
            f"{OPEN_API_BASE}/im/v1/messages/{parent_msg_id}/reply",
            headers=headers,
            json={
                "msg_type": "interactive",
                "content": json.dumps(_make_card(text), ensure_ascii=False)
            },
            timeout=10
        )
        if resp.status_code == 200:
            logger.info(f"Quoted reply sent to {parent_msg_id}")
            return True
        else:
            logger.error(f"Quoted reply failed: {resp.status_code} {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Quoted reply exception: {e}")
        return False


# ============ 工具定义 ============

def tool_query_member(keyword: str) -> str:
    return query_member(keyword)

def tool_get_roster_stats() -> str:
    return get_roster_stats()

def tool_query_roster_detail(work_type: str = "", status: str = "在职") -> str:
    return query_roster_detail(work_type=work_type, status=status)

def tool_update_member(name: str, field: str, value: str) -> str:
    return update_member(name=name, field=field, value=value)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_member",
            "description": "查询某个具体成员的详细信息，输入姓名或关键词",
            "parameters": {"type": "object", "properties": {"keyword": {"type": "string", "description": "成员姓名"}}, "required": ["keyword"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_roster_stats",
            "description": "获取公司总体人员统计数据（总人数、在职/离职数、各类型人数）",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_roster_detail",
            "description": "按工作类型和状态查询人员详细列表。例如：查实习生列表、查全职员工列表。work_type可选：全职/实习/兼职/顾问/代发/劳务；status可选：在职/离职归档",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_type": {"type": "string", "description": "工作类型，如：实习、全职、顾问"},
                    "status": {"type": "string", "description": "工作状态，默认在职", "default": "在职"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_member",
            "description": '更新名册中某成员的字段值并持久化保存。当用户说"张三换岗了"、"李四薪资调整为X"、"王五离职了"等，调用此工具更新信息。',
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "成员姓名"},
                    "field": {"type": "string", "description": "要更新的字段，如：职位、薪资、工作状态、部门、手机号等"},
                    "value": {"type": "string", "description": "新的字段值"}
                },
                "required": ["name", "field", "value"]
            }
        }
    }
]

AVAILABLE_FUNCTIONS = {
    "query_member": tool_query_member,
    "get_roster_stats": tool_get_roster_stats,
    "query_roster_detail": tool_query_roster_detail,
    "update_member": tool_update_member
}


# ============ 核心处理逻辑 ============

# 工作类型关键词（用于判断是否需要 LLM 处理，而非直接统计）
_WORK_TYPE_KEYWORDS = ["实习生", "实习", "全职", "兼职", "顾问", "代发", "劳务"]

def process_message(user_message: str, user_id: str, sender_name: str,
                    chat_id: str = "", msg_id: str = "") -> str:
    """处理用户消息"""
    logger.info(f"[{user_id}/{sender_name}] Processing: {user_message[:50]}")

    # 特殊命令
    if user_message.lower() in ["/clear", "清空", "忘记"]:
        llm_client_v2.conversation_manager.clear_history(user_id)
        with _pending_lock:
            _pending_contracts.pop(user_id, None)
        return "好的，之前的对话我都忘啦🙃"

    is_hr = is_hr_user(sender_name, user_id)

    # ── 合同追问状态（用户已发起合同但字段不全）──
    with _pending_lock:
        pending = _pending_contracts.get(user_id)

    if pending and not any(kw in user_message for kw in ["合同", "劳动合同", "劳务合同", "实习合同"]):
        # 把用户的补充内容合并到原始消息再重新处理
        merged = pending["original"] + " " + user_message
        with _pending_lock:
            _pending_contracts.pop(user_id, None)
        return handle_contract(merged, user_id, chat_id, msg_id)

    # 合同生成（仅HR）
    # 排除纯能力询问："能出合同吗"、"还能出合同吗"、"你会合同吗" 等 → 交给 LLM 回答
    _CONTRACT_INQUIRY_KWS = ["能", "会", "可以", "还能", "支持", "帮我", "能不能", "会不会", "可不可以"]
    _is_contract_inquiry = (
        any(kw in user_message for kw in _CONTRACT_INQUIRY_KWS)
        and not any(kw in user_message for kw in ["帮我出", "帮我生成", "帮我做", "生成", "出一份", "做一份", "起草"])
    )
    if any(kw in user_message for kw in ["合同", "劳动合同", "劳务合同", "实习合同"]):
        if _is_contract_inquiry:
            pass  # 能力询问，继续往下走交给 LLM
        elif not is_hr:
            return "合同生成功能仅限HR使用哦～"
        else:
            return handle_contract(user_message, user_id, chat_id, msg_id)

    # 入职查询 → 交给 LLM（知识库已内嵌在 system prompt 中，LLM 根据 is_hr 决定显示哪些内容）
    # （原 get_onboarding_info 已移除，LLM 直接回答）

    # 薪资敏感信息：HR 可查，非HR 拒绝
    if any(kw in user_message for kw in ["薪资", "工资", "底薪", "绩效", "涨薪", "薪酬", "到手", "用人成本"]):
        if not is_hr:
            return "薪资属于保密信息，具体请直接联系HR确认 🙏"
        names = re.findall(r'[\u4e00-\u9fa5]{2,4}', user_message)
        if names:
            return query_member(names[0], is_hr=True)
        return "请告诉我要查哪位同学的薪资信息～"

    # 名册精确查询（单人查询）—— 排除含工作类型词的群体查询
    _single_person_kws = ["是谁", "的资料", "的信息", "职位", "岗位", "身份证", "银行卡",
                          "电话", "手机", "联系方式", "联系电话", "手机号"]
    if (any(kw in user_message for kw in _single_person_kws)
            and not any(kw in user_message for kw in _WORK_TYPE_KEYWORDS + ["多少", "几个", "列表", "所有", "部门"])):
        names = re.findall(r'[\u4e00-\u9fa5]{2,4}', user_message)
        if names:
            return query_member(names[0], is_hr=is_hr)

    # 纯总人数统计（无具体类型词、无部门词时直接返回）
    _DEPT_KEYWORDS = ["部门", "部", "市场", "产品", "技术", "运营", "销售", "人力", "行政", "财务"]
    if any(kw in user_message for kw in ["多少人", "人数", "总人数", "统计"]):
        if not any(kw in user_message for kw in _WORK_TYPE_KEYWORDS + _DEPT_KEYWORDS):
            return get_roster_stats()

    # 其他（含复杂名册查询、实习生列表等）交给 LLM + 工具
    # per-request 闭包：query_member 携带 is_hr 上下文
    _available_functions = {
        "query_member": lambda keyword: query_member(keyword, is_hr=is_hr),
        "get_roster_stats": tool_get_roster_stats,
        "query_roster_detail": tool_query_roster_detail,
        "update_member": tool_update_member,
    }
    try:
        return llm_client_v2.chat_with_tools(
            user_message=user_message,
            user_id=user_id,
            tools=TOOLS,
            available_functions=_available_functions,
            is_hr=is_hr
        )
    except Exception as e:
        logger.error(f"LLM error: {e}")
        return "我现在有点忙，请稍后再试～"


def handle_contract(user_message: str, user_id: str = "",
                    chat_id: str = "", msg_id: str = "") -> str:
    """
    处理合同生成请求（支持多轮追问）。
    1. 识别合同类型
    2. LLM 提取字段
    3. 缺失必填字段时追问，保存待处理状态
    4. 字段完整时：列出字段摘要 → 后台生成 → 引用回复确认
    """
    contract_type = detect_contract_type(user_message)
    cn_name = CONTRACT_TYPE_NAMES[contract_type]

    # LLM 提取字段
    try:
        _, fields = extract_fields_via_llm(user_message, llm_client_v2)
    except Exception as e:
        logger.error(f"Field extraction failed: {e}")
        fields = {}

    # 必填字段校验
    required = {"name": "姓名", "job_title": "岗位名称", "salary": "薪资"}
    missing = [cn for k, cn in required.items()
               if not fields.get(k) or str(fields[k]).strip() in ("", "XXX")]

    if missing:
        # 保存待处理状态（用于下一条消息的补充）
        with _pending_lock:
            _pending_contracts[user_id] = {
                "original": user_message,
                "contract_type": contract_type,
            }
        return (f"收到你要生成「{cn_name}」的需求 ✅\n"
                f"还需要以下信息，补充后我马上生成：\n"
                + "\n".join(f"  • {m}" for m in missing))

    # 清除待处理状态
    with _pending_lock:
        _pending_contracts.pop(user_id, None)

    name = fields["name"]

    # 字段摘要（不展示合同内容，只列出提取到的信息）
    field_labels = {
        "name": "姓名", "job_title": "岗位名称", "salary": "薪资",
        "start_date": "入职日期", "duration": "合同时长", "id_number": "身份证号",
        "address": "联系地址", "hukou_address": "户籍地址",
    }
    summary_lines = [f"📋 合同信息确认："]
    summary_lines.append(f"  合同类型：{cn_name}")
    for k, label in field_labels.items():
        if fields.get(k) and str(fields[k]).strip() not in ("", "XXX"):
            summary_lines.append(f"  {label}：{fields[k]}")
    summary_lines.append(f"\n正在生成合同文档，稍后发送至 {DEFAULT_HR_EMAIL} ✉️")
    summary_text = "\n".join(summary_lines)

    # 后台生成 + 发邮件 + 引用回复确认
    def _background():
        try:
            fields.setdefault("sign_date", datetime.now().strftime("%Y-%m-%d"))
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

            # 引用回复确认（回复用户原消息）
            if msg_id:
                reply_to_message(msg_id, f"✅ {name}的{cn_name}已生成并发送至 {DEFAULT_HR_EMAIL}")
            elif chat_id:
                reply_text(chat_id, f"✅ {name}的{cn_name}已生成并发送至 {DEFAULT_HR_EMAIL}")
        except Exception as e:
            logger.error(f"Contract generation/send error: {e}", exc_info=True)
            if chat_id:
                reply_text(chat_id, f"❌ 合同生成失败，请检查模板或联系管理员：{str(e)[:100]}")

    threading.Thread(target=_background, daemon=True).start()
    return summary_text


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
        reply = process_message(text, user_id, sender_name, chat_id=chat_id, msg_id=msg_id)
        logger.info(f"Reply: {reply[:100]}")
        
        success = reply_text(chat_id, reply)
        if not success:
            logger.error("Failed to send reply")
    
    except Exception as e:
        logger.exception(f"Handle message error: {e}")


def handle_reaction_event(data) -> None:
    """忽略表情回应事件（避免 SDK 报 processor not found）"""
    pass


def handle_message_read_event(data) -> None:
    """忽略消息已读事件"""
    pass


def handle_message_updated_event(data) -> None:
    """忽略消息编辑/撤回事件"""
    pass


# 飞书事件处理器
handler = lark.EventDispatcherHandler.builder(ENCRYPT_KEY, VERIFICATION_TOKEN, lark.LogLevel.INFO) \
    .register_p2_im_message_receive_v1(handle_im_message) \
    .register_p2_im_message_reaction_created_v1(handle_reaction_event) \
    .register_p2_im_message_message_read_v1(handle_message_read_event) \
    .register_p2_im_message_recalled_v1(handle_message_updated_event) \
    .build()


@app.route("/event", methods=["POST"])
def event():
    """飞书事件入口 — 未注册的事件类型静默返回 200"""
    try:
        resp = handler.do(parse_req())
        return parse_resp(resp)
    except Exception as e:
        err = str(e)
        if "processor not found" in err:
            logger.debug(f"Unhandled event type (ignored): {err}")
            return {"code": 0}, 200
        logger.error(f"Event handler error: {e}")
        return {"code": 500}, 500


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
