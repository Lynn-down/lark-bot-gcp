"""
Lark 事件订阅服务：接收飞书消息事件，经业务逻辑处理后回复。
部署到 GCP VM 后，在飞书开发者后台配置「将事件发送至开发者服务器」并填写本服务的公网 URL。

Skill：意图识别模糊化 + 回复随机化
- 新增意图时用多组近义关键词，不用单一固定句式
- 所有回复、确认、提示均通过 _pick() 随机选一条，避免刻板
"""
import os
import re
import random
import json
import time
import logging
from flask import Flask

import requests
import lark_oapi as lark
from lark_oapi.adapter.flask import *
from lark_oapi.api.im.v1 import *

from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 从环境变量读取（未配置加密时传空字符串）
ENCRYPT_KEY = os.environ.get("LARK_ENCRYPT_KEY", "")
VERIFICATION_TOKEN = os.environ.get("LARK_VERIFICATION_TOKEN", "")
APP_ID = os.environ.get("LARK_APP_ID", "")
APP_SECRET = os.environ.get("LARK_APP_SECRET", "")

# 消息去重：飞书可能重复推送同一事件，避免重复回复
_MAX_PROCESSED = 5000
_processed_ids: set = set()

# --- 直接调用 OpenAPI 的轻量封装（用于 reaction / 历史消息 / 文档 raw_content） ---
OPEN_API_BASE = "https://open.feishu.cn/open-apis"
_token_cache = {"token": "", "expires_at": 0.0}


def _get_tenant_access_token() -> str:
    """获取 tenant_access_token（缓存到过期前 5 分钟）。"""
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
        raise RuntimeError(f"tenant_access_token failed: {data.get('msg')}")
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires_at"] = time.time() + float(data.get("expire", 7200))
    return _token_cache["token"]


def _open_api_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_tenant_access_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }


def add_reaction(message_id: str, emoji_type: str = "STRIVE") -> None:
    """
    给消息添加飞书内置表情回应（快捷表情）。
    “奋斗”对应 emoji_type=STRIVE（见表情文案说明）。
    """
    try:
        r = requests.post(
            f"{OPEN_API_BASE}/im/v1/messages/{message_id}/reactions",
            headers=_open_api_headers(),
            json={"reaction_type": {"emoji_type": emoji_type}},
            timeout=10,
        )
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code >= 400 or data.get("code") not in (0, None):
            logger.warning("add_reaction failed: status=%s body=%s", r.status_code, data or r.text)
    except Exception as e:
        logger.warning("add_reaction exception: %s", e)


def list_recent_messages(chat_id: str, page_size: int = 20) -> list[dict]:
    """拉取会话最近消息（按创建时间倒序）。"""
    r = requests.get(
        f"{OPEN_API_BASE}/im/v1/messages",
        headers=_open_api_headers(),
        params={
            "container_id_type": "chat",
            "container_id": chat_id,
            "page_size": page_size,
            "sort_type": "ByCreateTimeDesc",
        },
        timeout=10,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"list messages failed: {data.get('msg')}")
    return data.get("data", {}).get("items", []) or []


def get_message_by_id(message_id: str) -> dict | None:
    """按 message_id 获取消息详情。"""
    r = requests.get(
        f"{OPEN_API_BASE}/im/v1/messages/{message_id}",
        headers=_open_api_headers(),
        timeout=10,
    )
    data = r.json()
    if data.get("code") != 0:
        return None
    return data.get("data", {}).get("message")


# 飞书云文档链接：支持 feishu.cn / larksuite.com 的 docx/wiki/doc
DOC_URL_RE = re.compile(r"https?://[^\s?#]+/(?:docx|wiki|doc)/[A-Za-z0-9]+")


def _extract_text_from_message_item(item: dict) -> str:
    """
    从 im.message.list 的 item 提取可读文本（尽量）。
    支持 body.content / content，便于在文本中查找文档链接。
    """
    try:
        body = item.get("body") or {}
        content = body.get("content") or item.get("content") or ""
        msg_type = item.get("msg_type") or item.get("message_type") or ""
        if not content:
            return ""
        if isinstance(content, dict):
            return (content.get("text") or "").strip() or str(content)
        if msg_type == "text":
            data = json.loads(content) if isinstance(content, str) else {}
            return (data.get("text") if isinstance(data, dict) else content or "").strip() or content
        return str(content) if content else ""
    except Exception:
        return str(item.get("body") or item.get("content") or "")


def _find_latest_doc_url_in_text(text: str) -> str:
    m = DOC_URL_RE.search(text or "")
    return m.group(0) if m else ""


def _pick(arr: list) -> str:
    """随机选一条。每次回复通过多段 _pick 拼接，实现自行重生成。"""
    return random.choice(arr) if arr else ""


def read_docx_raw_content(doc_url_or_id: str) -> str:
    """读取 docx 纯文本（只支持 docx 文档）。"""
    m = re.search(r"/docx/([A-Za-z0-9]+)", doc_url_or_id)
    doc_id = m.group(1) if m else doc_url_or_id
    r = requests.get(
        f"{OPEN_API_BASE}/docx/v1/documents/{doc_id}/raw_content",
        headers=_open_api_headers(),
        timeout=15,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"raw_content failed: {data.get('msg')}")
    return (data.get("data", {}).get("content") or "").strip()


def reply_text(client: lark.Client, receive_id: str, receive_id_type: str, text: str) -> None:
    """向指定会话发送文本消息。"""
    req = CreateMessageRequest.builder() \
        .receive_id_type(receive_id_type) \
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(receive_id)
            .msg_type("text")
            .content(json.dumps({"text": text}))
            .build()
        ) \
        .build()
    resp = client.im.v1.message.create(req)
    if not resp.success():
        logger.error("send message failed: %s", resp.raw.content)


# 问候语关键词（含 @ 提及被替换成的 @_user_N，先去掉再匹配）
GREETING_KEYWORDS = (
    "你好", "嗨", "哈喽", "嘿", "早", "早上好", "下午好", "晚上好",
    "hi", "hello", "hey", "hiya", "yo",
)

# 常见问题：关键词 → 多组开头/主体/结尾，每次随机组合
_INTENT_FUNC = {
    "功能": (
        ["你能干什么", "你能做什么", "你的功能", "有什么功能", "会做什么", "你能干嘛", "你能干啥", "有什么本领"],
        [
            "嘿嘿，我呀可以跟你打招呼、聊聊天～", "我会跟你打招呼、聊今天、聊心情～",
            "目前就是聊聊天、回回问候啥的～", "我能跟你唠唠嗑、聊聊问候和心情～",
            "会打招呼、聊今天、聊心情～", "能聊问候、今天、心情这些～",
        ],
        [
            "你问我「今天怎么样」「介绍一下你自己」都行！以后还会越来越能干哒 ✨",
            "问「今天怎么样」或「介绍一下你自己」就行～ 后面还会加更多技能～",
            "试试问我「今天怎么样」「介绍一下你自己」！以后功能会越来越多 😄",
            "有啥想聊的尽管说～ 之后还会加新能力～",
        ],
    ),
    "今天": (
        ["今天怎么样", "今天如何", "今天好吗", "今天怎样", "今天好不好"],
        ["今天也超级好呀～", "今天不错哦～", "今天很好呀～", "今天挺不错～", "今天棒棒的～"],
        ["希望你今天也顺顺利利、开开心心的！☀️", "祝你一天都开开心心！", "你也加油，顺顺利利！", "你也顺顺利利呀！"],
    ),
    "介绍": (
        ["介绍一下你自己", "你是谁", "你叫什么", "自我介绍", "介绍下自己"],
        ["我是蹲在飞书里的一只小机器人～", "我是飞书里的小助手呀～", "一只在飞书里打工的小机器人～", "飞书里的小助手～"],
        [
            "会回你问候、聊聊今天、说说心情啥的，语气欢快的那种！有啥想聊的尽管说～",
            "能跟你打招呼、聊今天、聊心情，有啥想问的都可以跟我说～",
            "负责跟你唠唠嗑、回回问候、聊聊心情，想聊啥都行！",
            "跟你打招呼、聊今天、聊心情都行～ 想聊啥尽管说～",
        ],
    ),
    "心情": (
        ["心情怎么样", "你心情", "心情如何", "开心吗", "你开心吗", "心情好不好"],
        ["心情棒棒的！", "超好的～", "很好呀～", "挺开心的～", "不错呀～"],
        [
            "能在这儿跟你聊天就挺开心的～ 你也保持好心情呀！😊",
            "跟你聊天就开心！你也天天开心哦！",
            "能跟你说话就开心，你也要开开心心的！",
            "跟你聊就开心～ 你也保持好心情！",
        ],
    ),
}


def _normalize_text(raw_text: str) -> str:
    """去掉 @_user_N 等提及占位符，并收尾去空格、英文转小写。"""
    if not raw_text:
        return ""
    # 去掉 @_user_1、@_user_2 等
    text = re.sub(r"@_user_\d+\s*", "", raw_text).strip()
    return text.lower()


def _is_greeting(normalized: str) -> bool:
    """判断是否为问候（整句等于或以其开头）。"""
    if not normalized:
        return False
    for kw in GREETING_KEYWORDS:
        if normalized == kw or normalized.startswith(kw + " ") or normalized.startswith(kw + "!"):
            return True
    return False


def _get_sender_name(event) -> str:
    """从事件里尽量拿到发送者名称，拿不到则返回空。"""
    try:
        sender = getattr(event, "sender", None)
        if sender is None:
            return ""
        # 可能是 sender_id 下的 name，或顶层 name
        name = getattr(getattr(sender, "sender_id", None), "name", None) or getattr(sender, "name", None)
        return (name or "").strip()
    except Exception:
        return ""


def handle_im_message(data: P2ImMessageReceiveV1) -> None:
    """
    处理「接收消息」事件：被 @ 并问好时回复问候（私聊或群聊均可）。
    飞书要求 3 秒内返回 200，复杂逻辑建议异步处理后再发消息。
    """
    event = data.event
    message = event.message
    message_id = message.message_id

    # 去重：飞书可能重复推送同一消息事件，避免重复回复
    if message_id in _processed_ids:
        logger.info("skip duplicate event message_id=%s", message_id)
        return
    if len(_processed_ids) >= _MAX_PROCESSED:
        _processed_ids.clear()
    _processed_ids.add(message_id)

    chat_id = message.chat_id
    content = message.content
    parent_id = getattr(message, "parent_id", None) or ""
    # 文本消息 content 为 JSON 字符串，如 {"text":"用户输入"}，群聊可能含 @_user_1 等
    try:
        body = json.loads(content) if content else {}
        raw_text = (body.get("text") or "").strip()
    except Exception:
        raw_text = (content or "").strip()

    normalized = _normalize_text(raw_text)
    sender_name = _get_sender_name(event)
    logger.info("received message chat_id=%s message_id=%s normalized=%s", chat_id, message_id, normalized)

    # 1) 先对“收到的这条消息”点一个飞书内置表情（奋斗）
    #    如果权限不足或消息类型不支持，会在日志里提示，但不影响后续回复。
    add_reaction(message_id, "STRIVE")

    # ---------- 收到消息必回复：模糊意图识别 + 随机表述 ----------
    reply_content = None

    # 模糊意图：阅读文档（含 读/看看/查看/前文/上文/文档/链接 等）
    READ_DOC_KEYWORDS = (
        "阅读", "读", "看看", "查看", "打开", "读一下", "看看这个", "看看上面的", "前文", "上文",
        "上面发的", "刚才发的", "这个文档", "那个文档", "文档链接", "链接", "帮我读", "帮我看",
        "你读", "你看", "看一下", "读一下上面的", "前面的文档", "上面的链接", "看看链接", "打开链接",
        "看看文档", "阅读文档", "读文档", "看文档", "看一下文档", "阅读上文", "阅读前文",
    )
    want_read = any(k in normalized for k in READ_DOC_KEYWORDS)

    # 模糊意图：内化为技能（含 内化/技能/学/记住/吸收 等）
    SKILL_KEYWORDS = (
        "内化", "技能", "学一下", "记住", "总结成技能", "变成技能", "当作技能", "学习", "吸收",
        "纳入", "记下来", "学会", "掌握", "存成技能",
    )
    want_skill = any(k in normalized for k in SKILL_KEYWORDS)

    # 模糊意图：提炼/提取/总结（含 提炼/提取/总结/概括/要点 等）
    EXTRACT_KEYWORDS = (
        "提炼", "提取", "总结", "概括", "要点", "核心", "关键信息", "摘要", "归纳", "汇总",
    )
    want_extract = any(k in normalized for k in EXTRACT_KEYWORDS)

    # 2) 阅读文档：优先当前消息中的链接 → 引用消息 → 最近消息
    if want_read:
        try:
            doc_url = _find_latest_doc_url_in_text(raw_text)
            quoted_text = ""
            if parent_id:
                pm = get_message_by_id(parent_id) or {}
                quoted_text = _extract_text_from_message_item(pm) if pm else ""
            if not doc_url and quoted_text:
                doc_url = _find_latest_doc_url_in_text(quoted_text)
            if not doc_url:
                for it in list_recent_messages(chat_id, page_size=30):
                    if (it.get("message_id") or "") == message_id:
                        continue
                    doc_url = _find_latest_doc_url_in_text(_extract_text_from_message_item(it))
                    if doc_url:
                        break

            if doc_url and "/docx/" in doc_url:
                text_content = read_docx_raw_content(doc_url)
                excerpt = (text_content[:700] + "…") if len(text_content) > 700 else text_content
                reply_content = (
                    _pick(["我去看了", "读好啦", "看了", "读完了", "搞定", "收到", "看完啦", "搞定啦"])
                    + _pick(["你发的文档", "那份文档", "上面的文档", "这份文档"])
                    + "～\n\n"
                    + _pick(["开头一部分", "文档开头", "内容片段", "前面一段", "前面一小段"])
                    + f"：\n{excerpt}\n\n"
                    + _pick([
                        "你接下来想让我总结要点、提炼关键信息，还是按模板生成新文档？",
                        "需要我提炼要点、概括总结，还是按模板生成？",
                        "要我做哪一步：总结 / 提炼 / 按模板生成？",
                        "接下来你希望我总结、提炼，还是按模板生成？",
                        "要我帮你总结、提炼要点，还是按模板生成文档？",
                    ])
                )
            elif doc_url:
                reply_content = (
                    _pick(["找到链接了：", "看到链接了：", "链接在这："])
                    + f"{doc_url}\n\n"
                    + _pick([
                        "这个是 wiki/doc 类型，我目前主要支持 docx 纯文本读取。你希望我做什么？",
                        "不是 docx，我暂时只能读 docx～ 要不再发个 docx 我帮你读？",
                        "我目前主要支持 docx～ 你发个 docx 链接我就能读。",
                    ])
                )
            elif quoted_text:
                snippet = quoted_text[:600] + "…" if len(quoted_text) > 600 else quoted_text
                reply_content = (
                    _pick(["你引用的这条", "收到引用的内容", "这条消息"])
                    + f"：\n{snippet}\n\n"
                    + _pick([
                        "你希望我总结、提炼要点，还是按模板生成？",
                        "接下来要总结、提取，还是按模板生成文档？",
                        "要我做总结、提炼，还是按模板生成？",
                    ])
                )
            else:
                reply_content = _pick([
                    "我没在上文里找到文档链接～", "上文里没有可读的文档链接。",
                    "没找到文档链接～", "上文里没看到可读的链接。",
                ]) + _pick([
                    "你可以直接发链接，或者说「读一下上面那个」并引用那条消息。",
                    "你把文档链接发我一次，或引用带链接的消息再说「读」～",
                    "发个文档链接，或引用带链接的消息再说「读」～",
                ])
        except Exception as e:
            logger.exception("context read failed: %s", e)
            reply_content = _pick([
                "读文档时出错了，", "中途出错了～ ", "读取出错～ ",
            ]) + _pick([
                "你方便把链接再发一次吗？", "文档链接再发我一下，我再试～", "链接再发一次？",
            ])

    elif want_skill and not reply_content:
        reply_content = _pick([
            "你是想让我把这段话/文档内化成技能，", "想让我当技能记下来？",
            "收到～ 我会把内容当技能记下来，", "我会内化成技能，",
        ]) + _pick([
            "以后别人问相关问题时我能回答对。我先记下要点，有疑问你再说～",
            "之后有人问相关问题我会按这个来答。需要我再确认一遍吗？",
            "之后有人问我会按这个答～ 有疑问再说～",
        ])

    elif want_extract and not reply_content:
        reply_content = _pick([
            "你想让我提炼或总结内容～ ", "总结/提炼需要先有内容。",
            "提炼需要先有文档～ ", "要提炼的话，",
        ]) + _pick([
            "你先发我文档链接，或对已发的文档说「读一下」，我读了就能帮你提炼～",
            "发个文档链接，或对我说「读上面的文档」，我读完之后就能提炼～",
        ])

    if _is_greeting(normalized) and not reply_content:
        if sender_name:
            reply_content = (
                _pick(["你好呀，", "嗨 ", ""]) + f"{sender_name}"
                + _pick(["～ 很高兴见到你！", "～ 见到你真好！", " 你好呀～ 开心跟你聊天！"])
            )
        else:
            reply_content = _pick([
                "你好呀！很高兴见到你～", "嗨～ 见到你真好！", "你好呀！开心跟你聊天～",
                "嗨～ 很高兴见到你！", "你好～ 开心跟你聊天！",
            ])

    if not reply_content:
        for key, (kws, part1, part2) in _INTENT_FUNC.items():
            if any(kw in normalized for kw in kws):
                reply_content = _pick(part1) + _pick(part2)
                break

    client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()
    if reply_content is None:
        reply_content = _pick([
            "收到啦～ ", "收到～ ", "这句我还接不住～ ",
        ]) + _pick([
            "这句我还不太会接，你可以试试问我「你好」「你能干什么」或发文档让我「读一下」～",
            "试试问我「今天怎么样」或「介绍一下你自己」，也可以发文档说「读一下上面的」～",
            "问我「你好」「你能干什么」，或者发文档说「看看这个文档」都行～",
        ])

    reply_text(client, chat_id, "chat_id", reply_content)
    logger.info("replied to chat_id=%s", chat_id)


# 事件处理器：验签/解密由 SDK 根据 ENCRYPT_KEY、VERIFICATION_TOKEN 处理
handler = lark.EventDispatcherHandler.builder(ENCRYPT_KEY, VERIFICATION_TOKEN, lark.LogLevel.INFO) \
    .register_p2_im_message_receive_v1(handle_im_message) \
    .build()


@app.route("/event", methods=["POST"])
def event():
    """飞书事件推送入口。"""
    resp = handler.do(parse_req())
    return parse_resp(resp)


@app.route("/health", methods=["GET"])
def health():
    """健康检查，便于负载均衡或监控。"""
    return {"status": "ok"}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7777"))
    # 云服务器上需监听 0.0.0.0
    app.run(host="0.0.0.0", port=port, debug=False)
