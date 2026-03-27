"""
Lark HR 小机器人 - v5.4
"""
APP_VERSION = "v5.6-claude-opus"

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
from offboarding_generator import (
    generate_resignation_certificate,
    generate_termination_agreement,
    build_offboarding_email,
)
from roster_module import query_member, get_roster_stats, query_roster_detail, update_member, init_roster
from email_sender import send_contract_email, send_plain_email
from llm_client_v2 import llm_client_v2
from bitable_client import init_hr_board

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 配置
DEFAULT_HR_EMAIL = "jyx@group-ultra.com"
HR_USERS = ["蒋雨萱", "丁怡菲", "刘怡馨", "triplet", "戴祥和", "陈春宇", "陆俊豪"]
HR_USER_IDS = ["946d1fc5", "9ddfdb23", "9bbc73b9", "triplet", "dc84a3bd"]  # 946d1fc5=蒋雨萱 9ddfdb23=丁怡菲 9bbc73b9=刘怡馨 dc84a3bd=陆俊豪

# 待处理合同状态（多轮追问）user_id → {contract_type, fields, chat_id, msg_id}
_pending_contracts: Dict[str, Dict] = {}
_pending_lock = threading.Lock()

# 待处理离职状态（多轮追问）
_pending_offboardings: Dict[str, Dict] = {}
_pending_offboarding_lock = threading.Lock()

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


# 初始化 HR 看板 Bitable（必须在 get_access_token 定义之后）
_hr_board = init_hr_board(get_access_token)


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


def send_file_to_chat(chat_id: str, file_path: str, file_name: str) -> bool:
    """上传文件到飞书并发送到群聊"""
    try:
        token = get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        # 1. 上传文件，拿 file_key
        with open(file_path, "rb") as f:
            upload_resp = requests.post(
                f"{OPEN_API_BASE}/im/v1/files",
                headers=headers,
                data={"file_type": "stream", "file_name": file_name},
                files={"file": (file_name, f, "application/octet-stream")},
                timeout=30,
            )
        upload_data = upload_resp.json()
        logger.info(f"File upload response: {upload_data}")
        if upload_data.get("code") != 0:
            logger.error(f"File upload failed: {upload_data}")
            return False

        file_key = upload_data["data"]["file_key"]

        # 2. 发送文件消息到群
        send_resp = requests.post(
            f"{OPEN_API_BASE}/im/v1/messages?receive_id_type=chat_id",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "receive_id": chat_id,
                "msg_type": "file",
                "content": json.dumps({"file_key": file_key}),
            },
            timeout=15,
        )
        if send_resp.status_code == 200 and send_resp.json().get("code") == 0:
            logger.info(f"File '{file_name}' sent to {chat_id}")
            return True
        else:
            logger.error(f"File send failed: {send_resp.status_code} {send_resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"send_file_to_chat error: {e}")
        return False


def send_dm_to_user(target_user_id: str, text: str) -> bool:
    """发私信给指定 user_id 的用户"""
    try:
        headers = {
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            f"{OPEN_API_BASE}/im/v1/messages?receive_id_type=user_id",
            headers=headers,
            json={
                "receive_id": target_user_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("code") == 0:
            logger.info(f"DM sent to user {target_user_id}")
            return True
        else:
            logger.error(f"DM failed: {data}")
            return False
    except Exception as e:
        logger.error(f"send_dm_to_user error: {e}")
        return False


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

# ── HR 看板工具 ────────────────────────────────────────────────────────────────

def tool_query_interview(name: str = "", summary: bool = False) -> str:
    """查询 HR 看板面试记录"""
    if not _hr_board:
        return "HR看板暂不可用"
    if summary or not name:
        return _hr_board.summary_list()
    results = _hr_board.search_by_name(name)
    if not results:
        return f"HR看板中未找到与「{name}」相关的记录"
    return "\n\n".join(_hr_board.format_record(r) for r in results)

def tool_add_interview(fields: str) -> str:
    """新增一条面试记录到 HR 看板（fields 为 JSON 字符串）"""
    if not _hr_board:
        return "HR看板暂不可用"
    try:
        f = json.loads(fields) if isinstance(fields, str) else fields
    except Exception:
        return "字段格式错误，请传入 JSON"
    rid = _hr_board.create_record(f)
    if rid:
        return f"✅ 已在HR看板新增记录（ID: {rid}）"
    return "❌ 新增记录失败，请检查字段或稍后重试"

def tool_update_interview(name: str, fields: str) -> str:
    """更新 HR 看板中某候选人的记录（fields 为 JSON 字符串）"""
    if not _hr_board:
        return "HR看板暂不可用"
    records = _hr_board.search_by_name(name)
    if not records:
        return f"HR看板中未找到「{name}」的记录"
    try:
        f = json.loads(fields) if isinstance(fields, str) else fields
    except Exception:
        return "字段格式错误，请传入 JSON"
    record_id = records[0]["record_id"]
    ok = _hr_board.update_record(record_id, f)
    if ok:
        return f"✅ 已更新「{name}」的HR看板记录"
    return "❌ 更新失败，请稍后重试"

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
    },
    {
        "type": "function",
        "function": {
            "name": "query_interview",
            "description": "查询HR看板中的面试候选人信息。可按姓名查询某人详情，或不传姓名获取所有候选人概览。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "候选人姓名，不填则返回全部概览"},
                    "summary": {"type": "boolean", "description": "是否返回概览列表，默认false"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_interview",
            "description": '在HR看板新增一条面试候选人记录。fields为JSON字符串，可用字段：姓名、面试岗位、岗位性质、办公方式、一面日期与时间（格式"YYYY-MM-DD HH:MM"）、一面状态、一面视频、一面记录、结果、备注。',
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {"type": "string", "description": '候选人信息，JSON格式，如 {"姓名":"张三","面试岗位":"产品经理","状态":"待面试"}'}
                },
                "required": ["fields"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_interview",
            "description": "更新HR看板中某候选人的记录，如更新面试状态、结果、备注等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "候选人姓名"},
                    "fields": {"type": "string", "description": '要更新的字段，JSON格式，如 {"状态":"已面试","结果":"通过"}'}
                },
                "required": ["name", "fields"]
            }
        }
    }
]

AVAILABLE_FUNCTIONS = {
    "query_member": tool_query_member,
    "get_roster_stats": tool_get_roster_stats,
    "query_roster_detail": tool_query_roster_detail,
    "update_member": tool_update_member,
    "query_interview": tool_query_interview,
    "add_interview": tool_add_interview,
    "update_interview": tool_update_interview,
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
    _pending_reminder = None   # 若当前消息与合同无关，末尾附加提醒

    # ── 合同追问状态（用户已发起合同但字段不全）──
    with _pending_lock:
        pending = _pending_contracts.get(user_id)

    if pending:
        if pending.get("generated"):
            # 已生成过：只在用户明确补充/修改字段时重新生成（不受"合同"关键词限制）
            _update_kws = ["改", "换", "更新", "重新生成", "重新出", "把", "改成", "换成",
                           "加进", "加上", "修改", "调整", "入职", "签订", "日期", "薪资",
                           "地址", "身份证", "电话", "手机", "岗位", "时长"]
            if any(kw in user_message for kw in _update_kws):
                merged = pending["original"] + " " + user_message
                with _pending_lock:
                    _pending_contracts.pop(user_id, None)
                return handle_contract(merged, user_id, chat_id, msg_id)
            # 不是字段补充，不拦截，继续正常路由
        else:
            # 尚未生成过：用LLM判断是否是对这份合同的补充
            if _is_contract_related(user_message, pending):
                merged = pending["original"] + " " + user_message
                with _pending_lock:
                    _pending_contracts.pop(user_id, None)
                return handle_contract(merged, user_id, chat_id, msg_id)
            # LLM判断为无关：正常处理，但在末尾提醒用户合同还没完成
            _pending_reminder = pending

    # ── 离职追问状态 ──
    with _pending_offboarding_lock:
        _has_pending_ob = user_id in _pending_offboardings
    if _has_pending_ob:
        _unrelated = ["合同", "查一下", "多少人", "统计", "薪资",
                      "名册", "多维表格", "表格", "excel", "Excel",
                      "你现在", "你用的", "你是用", "你在用",
                      "哪个", "什么数据", "数据源",
                      "看板", "面试", "入职", "HR看板"]
        if not any(kw in user_message for kw in _unrelated):
            result = _continue_offboarding(user_message, user_id, chat_id, msg_id)
            if result is not None:
                return result

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

    # 离职流程（仅HR）
    _OFFBOARDING_KWS = ["离职", "解除合同", "终止合同", "辞职", "辞退", "最后工作日"]
    _OFFBOARDING_INQUIRY_KWS = ["能", "会", "可以", "支持", "什么是", "怎么", "流程", "步骤"]
    _is_offboarding_inquiry = any(kw in user_message for kw in _OFFBOARDING_INQUIRY_KWS)
    if any(kw in user_message for kw in _OFFBOARDING_KWS):
        if _is_offboarding_inquiry:
            pass  # 流程询问，交给 LLM 回答
        elif not is_hr:
            return "离职流程由HR处理，有疑问请联系HR～"
        else:
            return handle_offboarding(user_message, user_id, chat_id, msg_id)

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
        "query_interview": tool_query_interview,
        "add_interview": tool_add_interview,
        "update_interview": tool_update_interview,
    }
    try:
        reply = llm_client_v2.chat_with_tools(
            user_message=user_message,
            user_id=user_id,
            tools=TOOLS,
            available_functions=_available_functions,
            is_hr=is_hr
        )
        # 若用户有待处理合同但本条消息与合同无关，末尾附加提醒
        if _pending_reminder:
            p_name = _pending_reminder.get("name", "")
            p_cn   = CONTRACT_TYPE_NAMES.get(_pending_reminder.get("contract_type", ""), "合同")
            hint   = p_name + "的" + p_cn if p_name else p_cn
            reply  = reply + f"\n\n---\n对了，{hint}还没填完，需要继续的话跟我说～"
        return reply
    except Exception as e:
        logger.error(f"LLM error: {e}")
        return "我现在有点忙，请稍后再试～"


def _is_contract_related(user_message: str, pending: dict) -> bool:
    """LLM判断新消息是否是对待处理合同的补充（而非新话题或新合同请求）"""
    name = pending.get("name", "")
    contract_type = pending.get("contract_type", "labor")
    cn_name = CONTRACT_TYPE_NAMES.get(contract_type, "合同")
    context = f"「{cn_name}」" + (f"（当事人：{name}）" if name else "")
    messages = [
        {"role": "system", "content": (
            f"背景：HR正在出一份{context}，但信息还不完整（如缺少地址、身份证等），等待HR补充。\n"
            "请判断HR的新消息是否是在补充这份合同缺失的字段信息。\n"
            "回复 YES 的情况（必须同时满足：具体提供了某个字段的值）：\n"
            "  - 给出了日期、地址、身份证号、联系电话、薪资、岗位等具体数值\n"
            "  - 明确说'从名册取'/'帮我查一下'\n"
            "回复 NO 的情况（以下任一即为 NO）：\n"
            "  - 询问功能或能力（'你能出合同吗'、'有这个功能吗'、'你会做吗'）\n"
            "  - 发起全新合同请求（含'帮我出'、'出一份'、'做一份'、'生成'）\n"
            "  - 聊其他完全不相关的话题（天气、打招呼、闲聊等）\n"
            "  - 只说了人名但没有提供任何字段值\n"
            "只回复 YES 或 NO，不加任何解释。"
        )},
        {"role": "user", "content": user_message}
    ]
    try:
        resp = llm_client_v2._call_api(messages, tools=None, temperature=0, timeout=10)
        if "error" in resp:
            raise RuntimeError(resp["error"])
        answer = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip().upper()
        logger.info(f"[_is_contract_related] '{user_message[:30]}' -> {answer}")
        return answer.startswith("YES")
    except Exception as e:
        logger.warning(f"_is_contract_related LLM failed: {e}, defaulting to NO")
        # 超时/报错时保守处理：不拦截，让用户重新明确说明
        return False


def _enrich_contract_from_roster(name: str, fields: dict) -> None:
    """从名册自动填充合同字段（只补充缺失字段，不覆盖已有值）"""
    from roster_module import roster_manager as _rm
    if not _rm or not name:
        return
    person = _rm.query_by_name(name)
    if not person:
        return
    for roster_key, field_key in [
        ("身份证号",             "id_number"),
        ("收款银行预留手机号",   "phone"),
    ]:
        if not fields.get(field_key):
            val = person.get(roster_key, "")
            if val:
                fields[field_key] = val
    if not fields.get("phone"):
        fields["phone"] = person.get("手机号", "")
    logger.info(f"[Contract] Roster enriched for {name}: "
                f"id={'有' if fields.get('id_number') else '无'} "
                f"phone={'有' if fields.get('phone') else '无'}")


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

    # 从名册自动填充已知字段（身份证、手机号）
    if fields.get("name"):
        _enrich_contract_from_roster(fields["name"], fields)

    # 必填字段校验（按合同类型）
    salary_label = "日薪（数字，如：200）" if contract_type == "intern" else "月薪（数字，如：20000）"
    required = [
        ("name",              "姓名"),
        ("sign_date",         "签订日期（如：2026-04-01）"),
        ("id_number",         "身份证号码（18位）"),
        ("household_address", "户籍地址"),
        ("contact_address",   "联系地址"),
        ("phone",             "联系电话"),
        ("start_date",        "合同开始日期（如：2026-04-01）"),
        ("job_title",         "工作岗位"),
        ("salary",            salary_label),
    ]
    missing = [label for key, label in required
               if not fields.get(key) or str(fields[key]).strip() in ("", "XXX")]

    if missing:
        # 保存待处理状态（用于下一条消息的补充），包含已提取的名字供LLM意图判断使用
        with _pending_lock:
            _pending_contracts[user_id] = {
                "original": user_message,
                "contract_type": contract_type,
                "name": fields.get("name", ""),
            }
        return (f"收到你要生成「{cn_name}」的需求 ✅\n"
                f"还需要以下信息，补充后我马上生成：\n"
                + "\n".join(f"  • {m}" for m in missing))

    # 字段齐全，保留 pending（含已提取字段），方便事后更新
    with _pending_lock:
        _pending_contracts[user_id] = {
            "original": user_message,
            "contract_type": contract_type,
            "generated": True,   # 标记已生成过，可接受更新
        }

    name = fields["name"]

    # 字段摘要
    field_labels = {
        "name": "姓名", "job_title": "岗位", "salary": "薪资",
        "sign_date": "签订日期", "start_date": "开始日期",
        "id_number": "身份证号", "contact_address": "联系地址",
        "household_address": "户籍地址", "phone": "联系电话",
    }
    summary_lines = ["📋 合同信息确认：", f"  合同类型：{cn_name}"]
    for k, label in field_labels.items():
        if fields.get(k) and str(fields[k]).strip() not in ("", "XXX"):
            summary_lines.append(f"  {label}：{fields[k]}")
    summary_lines.append(f"\n正在生成合同文档，稍后直接发到此对话 ⬆️")
    summary_text = "\n".join(summary_lines)

    # 后台生成 + 发文件到飞书（失败时 fallback 邮件）
    def _background():
        try:
            fields.setdefault("sign_date", datetime.now().strftime("%Y-%m-%d"))
            fields.setdefault("work_location", "北京市")
            if contract_type == "labor":
                fields.setdefault("duration", "3")
                fields.setdefault("duration_unit", "年")
                fields.setdefault("probation_period", "3")
            elif contract_type == "service":
                fields.setdefault("duration", "3")
                fields.setdefault("duration_unit", "年")
            else:  # intern
                fields.setdefault("duration", "3")
                fields.setdefault("duration_unit", "月")
                fields["salary_type"] = "daily"   # 实习合同用日薪

            path = generate_contract(contract_type, fields, output_name=name)
            file_name = f"{name}-{cn_name}.docx"

            # 优先发到飞书聊天
            if chat_id:
                ok = send_file_to_chat(chat_id, path, file_name)
                if ok:
                    logger.info(f"Contract file sent to Lark chat: {path}")
                    return
                else:
                    logger.warning("Lark file send failed, falling back to email")

            # fallback：邮件
            send_contract_email(DEFAULT_HR_EMAIL, path, name, cn_name)
            logger.info(f"Contract sent by email: {path}")
            notify = f"✅ {name}的{cn_name}已生成（飞书发送失败，已发至 {DEFAULT_HR_EMAIL}）"
            if msg_id:
                reply_to_message(msg_id, notify)
            elif chat_id:
                reply_text(chat_id, notify)
        except Exception as e:
            logger.error(f"Contract generation/send error: {e}", exc_info=True)
            if chat_id:
                reply_text(chat_id, f"❌ 合同生成失败，请检查模板或联系管理员：{str(e)[:100]}")

    threading.Thread(target=_background, daemon=True).start()
    return summary_text


# ─── 离职流程 ────────────────────────────────────────────────────────────────

LYNN_USER_ID = "946d1fc5"   # 蒋雨萱（Lark权限通知 + 邮件fallback）

_OFFBOARDING_EXTRACT_PROMPT = (
    "从用户消息中提取离职相关字段，只返回纯 JSON，不加任何解释。\n"
    "可提取字段：\n"
    "  name              离职员工姓名\n"
    "  leave_date        拟解除/最后工作日 YYYY-MM-DD\n"
    "  start_date        入职日期 YYYY-MM-DD\n"
    "  job_title         职务/岗位\n"
    "  id_number         身份证号（18位）\n"
    "  phone             联系电话\n"
    "  compensation      经济补偿金，如'100000'/'无'（仅正职）\n"
    "  gender            性别（男/女）\n"
    "  bank_name         开户行（如：招商银行北京中关村支行）\n"
    "  bank_account      银行账号\n"
    "  bank_account_name 户名\n"
    "未明确提及的字段不要输出。"
)


def _extract_offboarding_fields(user_message: str) -> dict:
    """LLM提取离职相关字段"""
    current_year = datetime.now().year
    messages = [
        {"role": "system", "content": (
            _OFFBOARDING_EXTRACT_PROMPT +
            f"\n\n当前年份是 {current_year} 年。用户未明确说明年份时，默认为 {current_year} 年。"
        )},
        {"role": "user", "content": user_message},
    ]
    try:
        resp    = llm_client_v2._call_api(messages, tools=None, temperature=0)
        content = resp["choices"][0]["message"].get("content", "")
        content = re.sub(r'^```(?:json)?\s*', '', content.strip())
        content = re.sub(r'\s*```$', '', content)
        return json.loads(content)
    except Exception as e:
        logger.error(f"Offboarding field extraction failed: {e}")
        fields = {}
        m = re.search(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})', user_message)
        if m:
            fields["leave_date"] = (
                f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            )
        return fields


def _check_offboarding_missing(fields: dict) -> list:
    """返回正职离职缺失的必填字段列表（含说明）
    大部分字段已由 _enrich_from_roster 从名册补全，
    只有 compensation 和 gender 必须向用户询问。
    其余字段若名册里也没有，才额外追问。
    """
    missing = []
    if not fields.get("id_number"):
        missing.append("身份证号码")
    if not fields.get("phone"):
        missing.append("联系电话")
    if not fields.get("start_date"):
        missing.append("入职日期（如：2025年3月1日）")
    if not fields.get("job_title"):
        missing.append("职务/岗位名称")
    if "compensation" not in fields:
        missing.append('经济补偿金（有的话告知金额，没有回复"无"）')
    if not fields.get("gender"):
        missing.append("性别（男/女，用于离职证明）")
    if not fields.get("bank_name"):
        missing.append("开户行（银行名称及支行）")
    if not fields.get("bank_account"):
        missing.append("银行账号")
    return missing


def _enrich_from_roster(name: str, fields: dict) -> tuple:
    """从名册补充字段，返回 (work_type, emp_email)"""
    from roster_module import roster_manager as _rm
    person    = _rm.query_by_name(name) if _rm else None
    work_type = ""
    emp_email = ""
    if person:
        work_type = person.get("工作类型", "")
        emp_email = person.get("邮箱", "")
        for roster_key, field_key in [
            ("开始日期",                "start_date"),
            ("合同职务",                "job_title"),
            ("身份证号",                "id_number"),
            ("部门",                    "department"),
            ("收款银行",                "bank_name"),
            ("收款卡号",                "bank_account"),
            ("收款银行开户所在地址",    "bank_branch"),
        ]:
            if not fields.get(field_key):
                fields[field_key] = person.get(roster_key, "")
        if not fields.get("phone"):
            fields["phone"] = (person.get("手机号", "") or
                               person.get("收款银行预留手机号", ""))
        # 户名默认为本人姓名
        if not fields.get("bank_account_name") and name:
            fields["bank_account_name"] = name
    return work_type, emp_email


def _do_offboarding_bg(fields: dict, is_intern: bool,
                        emp_email: str, chat_id: str, msg_id: str):
    """后台生成离职文件、发邮件、通知蒋雨萱"""
    from offboarding_generator import _fmt_cn
    name     = fields.get("name", "")
    leave_cn = _fmt_cn(fields.get("leave_date", ""))

    def _bg():
        try:
            # ① 正职：生成协议 + 证明
            if not is_intern:
                try:
                    ag_path   = generate_termination_agreement(fields, output_name=name)
                    cert_path = generate_resignation_certificate(fields, output_name=name)
                    if chat_id:
                        send_file_to_chat(chat_id, ag_path,   f"{name}-离职协议.docx")
                        send_file_to_chat(chat_id, cert_path, f"{name}-离职证明.docx")
                except Exception as e:
                    logger.error(f"Offboarding doc error: {e}", exc_info=True)
                    if chat_id:
                        reply_text(chat_id, f"⚠️ 文档生成出错：{str(e)[:120]}")

            # ② 离职邮件
            subject, body = build_offboarding_email(fields)
            if emp_email:
                result = send_plain_email(emp_email, subject, body)
                if result["success"]:
                    if chat_id:
                        reply_text(chat_id, f"✅ 离职通知邮件已发送至 {emp_email}")
                else:
                    logger.warning(f"Email failed: {result['message']}")
                    _fallback_dm_lynn(name, subject, body)
            else:
                _fallback_dm_lynn(name, subject, body)

            # ③ 通知蒋雨萱关闭 Lark 权限
            send_dm_to_user(
                LYNN_USER_ID,
                f"提醒：{name} 最后工作日是 {leave_cn}，"
                f"记得到时候及时关闭 ta 的 Lark 权限哦 👌"
            )
        except Exception as e:
            logger.error(f"Offboarding bg error: {e}", exc_info=True)
            if chat_id:
                reply_text(chat_id, f"❌ 离职流程出错：{str(e)[:100]}")

    threading.Thread(target=_bg, daemon=True).start()


def handle_offboarding(user_message: str, user_id: str = "",
                       chat_id: str = "", msg_id: str = "") -> str:
    """处理离职请求（HR专属）。信息不全时追问，齐全后再生成。"""
    fields     = _extract_offboarding_fields(user_message)
    name       = fields.get("name", "")
    leave_date = fields.get("leave_date", "")

    if not name:
        return "请告诉我是谁要离职 😮"
    if not leave_date:
        # 保存不完整 pending，等下条消息补充
        with _pending_offboarding_lock:
            _pending_offboardings[user_id] = {
                "fields": {"name": name},
                "chat_id": chat_id, "msg_id": msg_id,
            }
        return f"收到，{name} 要离职——最后工作日是哪天？"

    work_type, emp_email = _enrich_from_roster(name, fields)
    fields["_work_type"] = work_type
    fields["_emp_email"] = emp_email
    is_intern = "实习" in work_type

    if is_intern:
        # 实习生只需 name + leave_date，直接生成
        _do_offboarding_bg(fields, True, emp_email, chat_id, msg_id)
        return (f"收到 **{name}**（实习生）离职申请 ✅\n"
                f"正在处理，稍后发到此对话 📄")

    # 正职：检查缺失字段
    missing = _check_offboarding_missing(fields)
    with _pending_offboarding_lock:
        _pending_offboardings[user_id] = {
            "fields": fields,
            "is_intern": False,
            "chat_id": chat_id, "msg_id": msg_id,
        }
    if missing:
        from offboarding_generator import _fmt_cn
        return (
            f"收到 **{name}**（正职）离职申请 ✅  最后工作日：{_fmt_cn(leave_date)}\n\n"
            f"还需要以下信息才能生成协议和证明，补充后我立刻处理：\n"
            + "\n".join(f"  • {m}" for m in missing)
        )
    else:
        # 信息已齐，生成
        with _pending_offboarding_lock:
            _pending_offboardings.pop(user_id, None)
        _do_offboarding_bg(fields, False, emp_email, chat_id, msg_id)
        return (f"收到 **{name}**（正职）离职申请 ✅\n"
                f"正在生成材料，稍后发到此对话 📄")


def _continue_offboarding(user_message: str, user_id: str,
                           chat_id: str, msg_id: str) -> str:
    """处理离职多轮追问中的补充/更新信息"""
    with _pending_offboarding_lock:
        state = _pending_offboardings.get(user_id)
    if not state:
        return None

    new_fields = _extract_offboarding_fields(user_message)
    # "无补偿"系列口语
    if any(kw in user_message for kw in
           ["无补偿", "无经济补偿", "不补偿", "没有补偿", "不需要补偿", "补偿为0", "补偿0"]):
        new_fields["compensation"] = "无"

    # 合并：新字段覆盖旧值
    state["fields"].update({k: v for k, v in new_fields.items() if v})
    fields = state["fields"]
    name   = fields.get("name", "")

    # 若之前还没有 leave_date（name-only pending）
    if not fields.get("leave_date"):
        return f"最后工作日是哪天？"

    # 补充 roster 信息（如还没补过）
    if "_work_type" not in fields:
        work_type, emp_email = _enrich_from_roster(name, fields)
        fields["_work_type"] = work_type
        fields["_emp_email"] = emp_email
        state["is_intern"] = "实习" in work_type

    is_intern = state.get("is_intern", False)
    emp_email = fields.get("_emp_email", "")

    if is_intern:
        with _pending_offboarding_lock:
            _pending_offboardings.pop(user_id, None)
        _do_offboarding_bg(fields, True, emp_email,
                           state["chat_id"], state["msg_id"])
        return f"信息齐了，正在处理 {name} 的离职，稍后发到此对话 📄"

    missing = _check_offboarding_missing(fields)
    if missing:
        return (
            "收到补充，还差：\n"
            + "\n".join(f"  • {m}" for m in missing)
        )

    # 全部齐了，生成
    with _pending_offboarding_lock:
        _pending_offboardings.pop(user_id, None)
    _do_offboarding_bg(fields, False, emp_email,
                       state["chat_id"], state["msg_id"])
    return f"信息齐了，正在生成 {name} 的离职材料，稍后发到此对话 📄"


def _fallback_dm_lynn(name: str, subject: str, body: str):
    """无法发邮件时把邮件内容私信蒋雨萱"""
    text = (
        f"📧 {name} 的离职通知邮件（未找到邮箱，请手动发送）\n\n"
        f"主题：{subject}\n\n{body}"
    )
    send_dm_to_user(LYNN_USER_ID, text)


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
            body = {}
            text = ""

        # 群聊只响应@提及
        chat_type = getattr(message, 'chat_type', 'p2p')
        if chat_type == "group":
            mentions = body.get("mentions", [])
            bot_open_id = "ou_bf1b5942e692731fd47e364343e44587"
            if not any(m.get("id", {}).get("open_id") == bot_open_id for m in mentions):
                logger.info("Group message without @mention, skipping")
                return

        if not text:
            logger.info("Empty message")
            return

        # 过期消息丢弃（防服务重启后重复处理 Feishu 重试包）
        create_time = getattr(message, 'create_time', None)
        if create_time:
            try:
                msg_ts = int(create_time) / 1000  # ms → s
                age = time.time() - msg_ts
                if age > 120:  # 超过 2 分钟的消息直接跳过
                    logger.info(f"Stale message (age {int(age)}s), skipping: {text[:30]}")
                    return
            except Exception:
                pass

        logger.info(f"Message from {sender_name}({user_id}): {text[:50]}")

        # 去重（同一次运行内防重复投递）
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
