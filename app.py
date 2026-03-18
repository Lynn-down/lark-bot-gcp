"""
Lark 事件订阅服务：接收飞书消息事件，经业务逻辑处理后回复。
部署到 GCP VM 后，在飞书开发者后台配置「将事件发送至开发者服务器」并填写本服务的公网 URL。
"""
import os
import re
import random
import json
import logging
from flask import Flask

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

# 常见问题/闲聊：(关键词列表, 回复文案列表)，每次随机选一条，语气欢快
INTENT_RESPONSES = (
    (
        ["你能干什么", "你能做什么", "你的功能", "有什么功能", "会做什么", "你能干嘛", "你能干啥", "有什么本领"],
        [
            "嘿嘿，我呀可以跟你打招呼、聊聊天～ 你问我「你能干什么」「今天怎么样」或者「介绍一下你自己」我都能接话！以后还会越来越能干哒 ✨",
            "我会跟你打招呼、聊今天、聊心情～ 问「今天怎么样」「介绍一下你自己」都行！后面还会加更多技能哒～",
            "目前就是聊聊天、回回问候啥的～ 你试试问我「今天怎么样」或「介绍一下你自己」！以后功能会越来越多的 😄",
        ],
    ),
    (
        ["今天怎么样", "今天如何", "今天好吗", "今天怎样", "今天好不好"],
        [
            "今天也超级好呀～ 希望你今天也顺顺利利、开开心心的！☀️",
            "今天不错哦～ 祝你一天都开开心心！",
            "今天很好呀～ 你也加油，顺顺利利！",
        ],
    ),
    (
        ["介绍一下你自己", "你是谁", "你叫什么", "自我介绍", "介绍下自己"],
        [
            "我是蹲在飞书里的一只小机器人～ 会回你问候、聊聊今天、说说心情啥的，语气还得欢快一点的那种！有啥想聊的尽管说～",
            "我是飞书里的小助手呀～ 能跟你打招呼、聊今天、聊心情，有啥想问的都可以跟我说～",
            "一只在飞书里打工的小机器人～ 负责跟你唠唠嗑、回回问候、聊聊心情，想聊啥都行！",
        ],
    ),
    (
        ["心情怎么样", "你心情", "心情如何", "开心吗", "你开心吗", "心情好不好"],
        [
            "心情棒棒的！能在这儿跟你聊天就挺开心的～ 你也保持好心情呀！😊",
            "超好的～ 跟你聊天就开心！你也天天开心哦！",
            "很好呀～ 能跟你说话就开心，你也要开开心心的！",
        ],
    ),
)


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
    chat_id = message.chat_id
    message_id = message.message_id
    content = message.content
    # 文本消息 content 为 JSON 字符串，如 {"text":"用户输入"}，群聊可能含 @_user_1 等
    try:
        body = json.loads(content) if content else {}
        raw_text = (body.get("text") or "").strip()
    except Exception:
        raw_text = (content or "").strip()

    normalized = _normalize_text(raw_text)
    sender_name = _get_sender_name(event)
    logger.info("received message chat_id=%s message_id=%s normalized=%s", chat_id, message_id, normalized)

    # ---------- 问候 + 常见问题/闲聊（随机选一条，语气欢快） ----------
    reply_content = None
    if _is_greeting(normalized):
        if sender_name:
            reply_content = random.choice([
                f"你好呀，{sender_name}～ 很高兴见到你！",
                f"嗨 {sender_name}～ 见到你真好！",
                f"{sender_name} 你好呀～ 开心跟你聊天！",
            ])
        else:
            reply_content = random.choice([
                "你好呀！很高兴见到你～",
                "嗨～ 见到你真好！",
                "你好呀！开心跟你聊天～",
            ])
    else:
        for keywords, responses in INTENT_RESPONSES:
            if any(kw in normalized for kw in keywords):
                reply_content = random.choice(responses)
                break

    if reply_content is None:
        # 未匹配到已知意图则不自动回复，避免刷屏
        return

    client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()
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
