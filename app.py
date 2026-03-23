"""
Lark HR 小机器人 - v3.0 LLM驱动架构
架构：输入 → LLM意图识别 → 调用工具 → LLM润色 → 输出回复

新功能：
- LLM智能意图识别
- 公司信息查询和更新
- 工具调用系统
- LLM润色回复
"""
APP_VERSION = "v4.0-llm-agent"

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

# 导入合同生成器
from contract_v2 import smart_extract_info, generate_labor_contract_v2
from roster_module import query_member, get_roster_stats, init_roster
from email_sender import send_contract_email
DEFAULT_HR_EMAIL = "jyx@group-ultra.com"
from lark_oapi.adapter.flask import *
from lark_oapi.api.im.v1 import *

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 最后生成的合同文件路径
_last_generated_contract = None
_last_email_status = None
# HR用户列表（可以访问入职流程TIPS详细内容）
HR_USERS = ["蒋雨萱", "丁怡菲", "刘怡馨", "triplet", "戴祥和", "陈春宇"]

def is_hr_user(sender_name, sender_id=""):
    """判断用户是否是HR"""
    if not sender_name:
        return False
    return any(hr_name in sender_name for hr_name in HR_USERS)


# ============ 配置读取 ============
ENCRYPT_KEY = os.environ.get("LARK_ENCRYPT_KEY", "")
VERIFICATION_TOKEN = os.environ.get("LARK_VERIFICATION_TOKEN", "")
APP_ID = os.environ.get("LARK_APP_ID", "")
APP_SECRET = os.environ.get("LARK_APP_SECRET", "")

# LLM API 配置
LLM_API_URL = os.environ.get("LLM_API_URL", "https://api.ablai.top/token")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

# 文件路径
COMPANY_INFO_FILE = os.path.join(os.path.dirname(__file__), "company_info.json")

# 飞书 API 基础地址
OPEN_API_BASE = "https://open.feishu.cn/open-apis"
_token_cache = {"token": "", "expires_at": 0.0}

# 消息去重
_MAX_PROCESSED = 5000
_processed_ids: set = set()
_processed_lock = threading.Lock()

# ============ LLM API 调用模块 ============

class LLMClient:
    """LLM API 客户端"""
    
    def __init__(self, api_url: str, api_key: str, model: str):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    def chat_completion(
        self, 
        messages: List[Dict[str, str]], 
        temperature: float = 0.7,
        max_tokens: int = 1000,
        tools: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """调用 LLM API 进行对话"""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        
        try:
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            return {"error": str(e)}
    
    def recognize_intent(self, user_message: str, context: str = "") -> Dict[str, Any]:
        """
        使用 LLM 识别用户意图
        返回: {"intent": "意图类型", "parameters": {...}, "confidence": 0.9}
        """
        system_prompt = """你是一个HR助手的意图识别模块。请分析用户消息，识别其意图并提取参数。

支持的意图类型：
1. query_company_info - 查询公司信息（如公司介绍、联系方式、部门信息、规章制度、入职流程、入职材料等）
2. update_company_info - 更新公司信息（如修改联系方式、添加新政策、更新FAQ等）
3. generate_contract - 生成合同（仅限HR使用），格式："生成劳动合同/劳务合同/实习合同，姓名：xxx，岗位：xxx，工资：xxx..."
3. read_document - 读取并分析飞书云文档/表格
4. summarize_document - 总结文档内容
5. generate_from_template - 根据模板生成文档
6. greeting - 问候/闲聊
7. ask_function - 询问功能/帮助
8. other - 其他意图

请严格按JSON格式返回：
{
    "intent": "意图类型",
    "parameters": {"key": "value"},
    "confidence": 0.95,
    "reasoning": "识别理由"
}"""

        user_prompt = f"用户消息：{user_message}"
        if context:
            user_prompt += f"\n上下文：{context}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response = self.chat_completion(messages, temperature=0.3, max_tokens=500)
        
        if "error" in response:
            return {"intent": "other", "parameters": {}, "confidence": 0.0, "error": response["error"]}
        
        try:
            content = response["choices"][0]["message"]["content"]
            # 提取 JSON 部分
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result
            return {"intent": "other", "parameters": {}, "confidence": 0.0}
        except Exception as e:
            logger.error(f"Failed to parse intent: {e}")
            return {"intent": "other", "parameters": {}, "confidence": 0.0}
    
    def polish_response(
        self, 
        raw_response: str, 
        user_message: str, 
        intent: str,
        tone: str = "friendly_professional"
    ) -> str:
        """
        使用 LLM 润色回复内容
        tone: friendly_professional(友好专业), formal(正式), casual(随意)
        """
        tone_prompts = {
            "friendly_professional": "你是一位友好专业的HR助手，语气亲切但保持专业，适合日常员工沟通。",
            "formal": "你是一位正式的HR助手，语气庄重规范，适合发布重要通知。",
            "casual": "你是一位随和的HR助手，语气轻松活泼，适合闲聊和日常问答。"
        }
        
        system_prompt = f"""{tone_prompts.get(tone, tone_prompts["friendly_professional"])}

你的任务是将原始回复润色成自然、流畅的中文回复。要求：
1. 保持信息的准确性和完整性
2. 语气亲切自然，像同事间对话，减少"请问"、"您好"等客气语
3. 可以适当使用表情符号
4. 结构清晰
5. 直接输出润色后的回复，不要解释
6. 回复简洁直接"""

        user_prompt = f"""用户消息：{user_message}
识别意图：{intent}

原始回复内容：
{raw_response}

请润色以上回复："""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response = self.chat_completion(messages, temperature=0.8, max_tokens=800)
        
        if "error" in response:
            return raw_response
        
        try:
            polished = response["choices"][0]["message"]["content"].strip()
            # 清理 markdown 符号
            polished = _clean_markdown(polished)
            return polished if polished else _clean_markdown(raw_response)
        except:
            return _clean_markdown(raw_response)

# 初始化 LLM 客户端
llm_client = LLMClient(LLM_API_URL, LLM_API_KEY, LLM_MODEL)

# ============ 公司信息管理模块 ============

class CompanyInfoManager:
    """公司信息管理器 - 支持查询和更新"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.data = self._load_data()
    
    def _load_data(self) -> Dict:
        """加载公司信息"""
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load company info: {e}")
        return self._get_default_data()
    
    def _save_data(self):
        """保存公司信息"""
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save company info: {e}")
    
    def _get_default_data(self) -> Dict:
        """获取默认数据结构"""
        return {
            "company": {
                "name": "",
                "description": "",
                "address": "",
                "contact": {"phone": "", "email": ""}
            },
            "departments": [],
            "policies": [],
            "faqs": [],
            "announcements": [],
            "version": "1.0.0",
            "last_updated": datetime.now().isoformat()
        }
    
    def query_info(self, query_type: str, keyword: str = "", user_dept: str = "") -> str:
        """
        查询公司信息 - 只返回匹配的信息
        """
        keyword_lower = (keyword or "").lower()
        
        # 如果是入职相关查询，优先返回入职信息
        if query_type == "onboarding" or any(k in keyword_lower for k in ["入职", "新员工", "报到"]):
            return self._get_onboarding_info(keyword, user_dept)
        
        # 公司信息查询
        if query_type in ["company", "all"]:
            company = self.data.get("company", {})
            
            # 没有关键词 -> 只返回名称和地址
            if not keyword:
                return "公司名称：" + company.get('name', 'N/A') + "\n公司地址：" + company.get('address', 'N/A')
            
            # 地址查询
            if any(k in keyword_lower for k in ["地址", "在哪", "位置", "location", "addr"]):
                return "公司地址：" + company.get('address', 'N/A')
            
            # 联系方式查询
            if any(k in keyword_lower for k in ["电话", "手机", "联系", "email", "邮箱", "邮件"]):
                email = company.get('contact', {}).get('email', 'N/A')
                return "联系邮箱：" + email
            
            # 简介/介绍查询
            if any(k in keyword_lower for k in ["简介", "介绍", "做什么", "业务", "about", "产品", "intent"]):
                return "公司名称：" + company.get('name', 'N/A') + "\n公司简介：" + company.get('description', 'N/A') + "\n主营业务：" + company.get('business', 'N/A')
            
            # 官网查询
            if any(k in keyword_lower for k in ["网站", "官网", "website", "网址", "主页"]):
                return "公司官网：" + company.get('website', 'N/A')
            
            # 默认返回核心信息
            return "公司名称：" + company.get('name', 'N/A') + "\n公司地址：" + company.get('address', 'N/A')
        
        # 部门查询 - 只返回匹配的部门
        if query_type == "department":
            departments = self.data.get("departments", [])
            matched = []
            for dept in departments:
                if keyword_lower in dept.get('name', '').lower():
                    matched.append("【" + dept.get('name', 'N/A') + "】" + dept.get('description', 'N/A') + "\n联系方式：" + dept.get('contact', 'N/A'))
            if matched:
                return "\n\n".join(matched[:2])
            return "未找到相关部门信息。"
        
        # 政策查询 - 只返回匹配的政策
        if query_type == "policy":
            policies = self.data.get("policies", [])
            matched = []
            for policy in policies:
                if keyword_lower in policy.get('title', '').lower():
                    matched.append("【" + policy.get('title', 'N/A') + "】\n" + policy.get('content', 'N/A'))
            if matched:
                return "\n\n".join(matched[:2])
            return "未找到相关制度信息。"
        
        # FAQ查询 - 只返回匹配的FAQ
        if query_type == "faq":
            faqs = self.data.get("faqs", [])
            matched = []
            for faq in faqs:
                if keyword_lower in faq.get('question', '').lower():
                    matched.append("Q: " + faq.get('question', 'N/A') + "\nA: " + faq.get('answer', 'N/A'))
            if matched:
                return "\n\n".join(matched[:2])
            return "未找到相关问答。"
        
        # 默认返回核心公司信息
        company = self.data.get("company", {})
        return "公司名称：" + company.get('name', 'N/A') + "\n公司地址：" + company.get('address', 'N/A')

    def _get_onboarding_info(self, keyword: str = "", user_dept: str = "") -> str:
        """获取入职相关信息，区分HR和普通员工"""
        results = []
        onboarding = self.data.get("onboarding", {})
        
        # 判断是否是HR部门
        is_hr = user_dept and "hr" in user_dept.lower()
        
        if keyword:
            keyword_lower = keyword.lower()
            
            # 入职前准备
            if any(k in keyword_lower for k in ["准备", "材料", "带什么", "电子材料"]):
                materials = onboarding.get("before_entry", {}).get("electronic_materials", [])
                results.append("入职前请准备以下电子版材料：")
                for i, item in enumerate(materials, 1):
                    results.append(f"{i}. {item}")
                entry_materials = onboarding.get("entry_day", {}).get("materials", [])
                results.append("\n入职当天请携带：")
                for i, item in enumerate(entry_materials, 1):
                    results.append(f"{i}. {item}")
            
            # 入职流程
            elif any(k in keyword_lower for k in ["流程", "步骤", "过程", "怎么办"]):
                if is_hr:
                    # HR 看到详细流程
                    process = onboarding.get("entry_day", {}).get("process", [])
                    results.append("新员工入职流程（HR操作）：")
                    for i, step in enumerate(process, 1):
                        results.append(f"{i}. {step}")
                    contract = onboarding.get("before_entry", {}).get("contract_info", "")
                    if contract:
                        results.append(f"\n合同信息：{contract}")
                else:
                    # 普通员工看到简化流程
                    results.append("入职当天流程：")
                    results.append("1. 上午10点到公司（东升大厦A座4楼）")
                    results.append("2. 楼下联系门卫开门，电梯上四楼")
                    results.append("3. 找HR接待并安排工位")
                    results.append("4. 签署劳动合同")
                    results.append("5. 配置Lark（飞书）账号")
                    results.append("6. 领取入职指引手册")
                    results.append("\n如有疑问请联系HR：hr@group-ultra.com")
            
            # 入职时间/地点
            elif any(k in keyword_lower for k in ["时间", "几点", "什么时候"]):
                time_info = onboarding.get("entry_day", {}).get("time", "上午10点")
                location = onboarding.get("entry_day", {}).get("location", "东升大厦A座4楼")
                results.append(f"入职时间：{time_info}")
                results.append(f"入职地点：{location}")
            
            else:
                # 通用入职信息
                results.append("入职相关信息：")
                time_info = onboarding.get("entry_day", {}).get("time", "上午10点")
                location = onboarding.get("entry_day", {}).get("location", "东升大厦A座4楼")
                results.append(f"入职时间：{time_info}")
                results.append(f"入职地点：{location}")
                results.append("\n如需了解详细流程，请告诉我你想知道什么，比如：")
                results.append("- 入职需要准备什么材料？")
                results.append("- 入职流程是什么？")
        else:
            # 没有关键词时返回入职概览
            if is_hr:
                results.append("【HR入职管理】")
                process = onboarding.get("entry_day", {}).get("process", [])
                results.append(f"入职流程共 {len(process)} 个步骤")
                results.append("\n可查询：入职准备材料、入职流程、合同信息等")
            else:
                results.append("【新员工入职指南】")
                time_info = onboarding.get("entry_day", {}).get("time", "上午10点")
                location = onboarding.get("entry_day", {}).get("location", "东升大厦A座4楼")
                results.append(f"入职时间：{time_info}")
                results.append(f"入职地点：{location}")
                results.append("\n常见问题：")
                results.append("- 入职需要带什么？")
                results.append("- 入职流程是什么？")
                results.append("\n如有疑问请联系HR：hr@group-ultra.com")
        
        return "\n".join(results) if results else "暂无入职相关信息。"


    
    def update_info(self, update_type: str, data: Dict) -> str:
        """
        更新公司信息
        update_type: company, department, policy, faq, announcement
        """
        try:
            if update_type == "company":
                self.data["company"].update(data)
            elif update_type == "department":
                self.data["departments"].append(data)
            elif update_type == "policy":
                self.data["policies"].append(data)
            elif update_type == "faq":
                self.data["faqs"].append(data)
            elif update_type == "announcement":
                data["date"] = datetime.now().strftime("%Y-%m-%d")
                self.data["announcements"].append(data)
            else:
                return f"不支持的更新类型：{update_type}"
            
            self.data["last_updated"] = datetime.now().isoformat()
            self._save_data()
            return f"✅ 已成功更新 {update_type} 信息！"
        except Exception as e:
            logger.error(f"Update failed: {e}")
            return f"❌ 更新失败：{str(e)}"
    
    def get_all_info_summary(self) -> str:
        """获取所有信息的摘要"""
        summary = []
        company = self.data.get("company", {})
        summary.append(f"公司：{company.get('name', 'N/A')}")
        summary.append(f"部门数量：{len(self.data.get('departments', []))}")
        summary.append(f"制度数量：{len(self.data.get('policies', []))}")
        summary.append(f"FAQ数量：{len(self.data.get('faqs', []))}")
        summary.append(f"公告数量：{len(self.data.get('announcements', []))}")
        summary.append(f"最后更新：{self.data.get('last_updated', 'N/A')}")
        return "\n".join(summary)

# 初始化公司信息管理器
company_manager = CompanyInfoManager(COMPANY_INFO_FILE)

# 初始化名册管理器
init_roster()

# ============ 工具函数定义 ============

class ToolRegistry:
    """工具注册中心"""
    
    def __init__(self):
        self.tools: Dict[str, Callable] = {}
        self.tool_schemas: List[Dict] = []
    
    def register(self, name: str, description: str, parameters: Dict):
        """注册工具的装饰器"""
        def decorator(func: Callable):
            self.tools[name] = func
            self.tool_schemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters
                }
            })
            return func
        return decorator
    
    def get_schemas(self) -> List[Dict]:
        return self.tool_schemas
    
    def execute(self, tool_name: str, parameters: Dict) -> str:
        """执行工具"""
        if tool_name not in self.tools:
            return f"工具 {tool_name} 未找到"
        try:
            result = self.tools[tool_name](**parameters)
            return str(result)
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return f"工具执行失败：{str(e)}"

tool_registry = ToolRegistry()

# 注册工具
@tool_registry.register(
    name="query_company_info",
    description="查询公司信息，包括公司介绍、部门信息、规章制度、FAQ、入职信息等。支持查询：公司地址、联系方式、入职流程、入职材料、部门信息、规章制度、常见问题等",
    parameters={
        "type": "object",
        "properties": {
            "query_type": {
                "type": "string",
                "enum": ["company", "department", "policy", "faq", "announcement", "onboarding", "all"],
                "description": "查询类型：company-公司信息, department-部门信息, policy-规章制度, faq-常见问题, onboarding-入职信息, all-所有"
            },
            "keyword": {
                "type": "string",
                "description": "关键词，用于精确筛选，如：地址、入职流程、WiFi密码等"
            },
            "user_dept": {
                "type": "string",
                "description": "用户所在部门，用于判断权限",
                "default": ""
            }
        },
        "required": ["query_type"]
    }
)
def query_company_info(query_type: str, keyword: str = "", user_dept: str = "") -> str:
    return company_manager.query_info(query_type, keyword, user_dept)

@tool_registry.register(
    name="update_company_info",
    description="更新公司信息，需要管理员权限",
    parameters={
        "type": "object",
        "properties": {
            "update_type": {
                "type": "string",
                "enum": ["company", "department", "policy", "faq", "announcement"],
                "description": "更新类型"
            },
            "data": {
                "type": "object",
                "description": "更新的数据内容"
            }
        },
        "required": ["update_type", "data"]
    }
)
def update_company_info(update_type: str, data: Dict) -> str:
    return company_manager.update_info(update_type, data)

@tool_registry.register(
    name="get_current_time",
    description="获取当前时间",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)
def get_current_time() -> str:
    return datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")

@tool_registry.register(
    name="get_company_summary",
    description="获取公司信息摘要",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)
def get_company_summary() -> str:
    return company_manager.get_all_info_summary()

@tool_registry.register(
    name="query_member",
    description="Query member info by name or position",
    parameters={
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "Name or position to search"
            }
        },
        "required": ["keyword"]
    }
)
def tool_query_member(keyword: str) -> str:
    return query_member(keyword)

@tool_registry.register(
    name="get_roster_stats",
    description="Get roster statistics",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)
def tool_get_roster_stats() -> str:
    return get_roster_stats()

# ============ 飞书 API 工具函数 ============

def _get_tenant_access_token() -> str:
    """获取 tenant_access_token（缓存到过期前 5 分钟）"""
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
    """给消息添加飞书内置表情回应"""
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


def reply_text(client: lark.Client, receive_id: str, receive_id_type: str, text: str) -> None:
    """向指定会话发送文本消息"""
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


# ============ 文档读取功能（保留原有功能）===========

DOC_URL_RE = re.compile(
    r"https?://[^\s?#]+/(?:docx|wiki|doc|sheets|base)/[A-Za-z0-9_-]+"
)


def _read_docx(url_or_id: str) -> str:
    """读取 docx 云文档纯文本"""
    m = re.search(r"/docx/([A-Za-z0-9_-]+)", url_or_id)
    doc_id = m.group(1) if m else url_or_id
    r = requests.get(
        f"{OPEN_API_BASE}/docx/v1/documents/{doc_id}/raw_content",
        headers=_open_api_headers(),
        timeout=15,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"docx raw_content failed: {data.get('msg')}")
    return (data.get("data", {}).get("content") or "").strip()


def _read_doc(url_or_id: str) -> str:
    """读取旧版 doc 云文档纯文本"""
    m = re.search(r"/doc/([A-Za-z0-9_-]+)", url_or_id)
    doc_token = m.group(1) if m else url_or_id
    r = requests.get(
        f"{OPEN_API_BASE}/doc/v2/{doc_token}/raw_content",
        headers=_open_api_headers(),
        timeout=15,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"doc raw_content failed: {data.get('msg')}")
    return (data.get("data", {}).get("content") or "").strip()


def _read_sheet(url: str) -> str:
    """读取云表格"""
    m = re.search(r"/sheets/([A-Za-z0-9_-]+)", url)
    if not m:
        raise ValueError("invalid sheet URL")
    spreadsheet_token = m.group(1)
    sheet_id = ""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    sheet_id = (qs.get("sheet", [""]) or [""])[0]
    if not sheet_id:
        r = requests.get(
            f"{OPEN_API_BASE}/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query",
            headers=_open_api_headers(),
            timeout=15,
        )
        meta = r.json()
        if meta.get("code") == 0:
            d = meta.get("data") or {}
            sheets = d.get("sheets") or d.get("items") or []
            if sheets:
                sheet_id = sheets[0].get("sheet_id", "")
    if not sheet_id:
        raise RuntimeError("could not get sheet_id")
    range_str = f"{sheet_id}!A1:Z500"
    r = requests.get(
        f"{OPEN_API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}/values/{range_str}",
        headers=_open_api_headers(),
        params={"valueRenderOption": "ToString", "dateTimeRenderOption": "FormattedString"},
        timeout=15,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"sheet values failed: {data.get('msg')}")
    values = data.get("data", {}).get("valueRange", {}).get("values") or []
    lines = ["\t".join(str(c) for c in row) for row in values]
    return "\n".join(lines).strip()


def read_document_content(doc_url: str) -> str:
    """根据链接类型读取云文档内容"""
    doc_url = (doc_url or "").strip()
    if not doc_url:
        raise ValueError("empty doc_url")
    if "/docx/" in doc_url:
        return _read_docx(doc_url)
    if "/doc/" in doc_url:
        return _read_doc(doc_url)
    if "/sheets/" in doc_url:
        return _read_sheet(doc_url)
    raise ValueError(f"unsupported doc URL type: {doc_url[:80]}")


# ============ 核心处理逻辑 ============


def _clean_markdown(text: str) -> str:
    """清理 markdown 符号，返回纯文本"""
    if not text:
        return text
    # 移除标题符号 #
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    # 移除加粗/斜体符号 * 和 _
    text = re.sub(r'\*\*?|__?', '', text)
    # 移除列表符号 - 和 *
    text = re.sub(r'^[\s]*[-*]\s+', '', text, flags=re.MULTILINE)
    # 移除数字列表 1. 2. 等
    text = re.sub(r'^[\s]*\d+\.\s+', '', text, flags=re.MULTILINE)
    # 移除代码块 ```
    text = re.sub(r'```\w*\n?', '', text)
    text = re.sub(r'```', '', text)
    # 移除行内代码 `
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # 移除链接 [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # 移除多余空行
    text = re.sub(r'\n\n\n+', '\n\n', text)
    return text.strip()

def _normalize_text(raw_text: str) -> str:
    """去掉 @_user_N 等提及占位符"""
    if not raw_text:
        return ""
    text = re.sub(r"@_user_\d+\s*", "", raw_text).strip()
    return text.lower()


def _get_sender_info(event):
    """从事件里获取发送者信息"""
    try:
        sender = getattr(event, "sender", None)
        if sender is None:
            return {"name": "", "id": ""}
        sender_id_obj = getattr(sender, "sender_id", None)
        user_id = getattr(sender_id_obj, "user_id", "") if sender_id_obj else ""
        name = getattr(sender_id_obj, "name", None) or getattr(sender, "name", None) or ""
        return {"name": name.strip(), "id": user_id}
    except Exception:
        return {"name": "", "id": ""}

def _get_sender_name(event) -> str:
    """从事件里获取发送者名称（兼容旧代码）"""
    return _get_sender_info(event).get("name", "")


def process_with_llm(user_message: str, sender_name: str, sender_id: str = "") -> str:
    """
    使用 LLM 架构处理用户消息：
    1. 意图识别
    2. 工具调用
    3. 润色回复
    """
    # Step 1: LLM 意图识别
    logger.info(f"Processing message: {user_message[:50]}...")
    intent_result = llm_client.recognize_intent(user_message)
    logger.info(f"Intent recognized: {intent_result}")
    
    intent = intent_result.get("intent", "other")
    parameters = intent_result.get("parameters", {})
    
    # 判断是否是HR用户
    is_hr = is_hr_user(sender_name, sender_id)
    
    # Step 2: 根据意图执行相应操作
    
    # 合同生成特殊处理：直接返回，不经过LLM润色
    if intent == "generate_contract":
        if not is_hr:
            return "合同生成功能仅限HR使用~"
        
        import re
        from datetime import datetime
        
        contract_data = {}
        msg = user_message
        
        # 提取员工姓名
        name_match = re.search(r"(?:姓名|叫|是)?[\s:：]*([\u4e00-\u9fa5]{2,4})(?:的|要|入职)?", msg)
        if name_match:
            contract_data["员工姓名"] = name_match.group(1).strip()
        
        # 提取岗位
        pos_match = re.search(r"(?:岗位|职位|做|当|担任)[\s:：]*([\u4e00-\u9fa5a-zA-Z]{2,15})", msg)
        if pos_match:
            contract_data["岗位名称"] = pos_match.group(1).strip()
        
        # 提取工资
        salary_match = re.search(r"(\d{4,6})[\s元\/月]*", msg)
        if salary_match:
            contract_data["税前工资"] = salary_match.group(1)
        
        # 提取日期
        date_match = re.search(r"(\d{4})[-\/年](\d{1,2})[-\/月](\d{1,2})", msg)
        if date_match:
            contract_data["签订日期"] = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
        else:
            contract_data["签订日期"] = datetime.now().strftime("%Y-%m-%d")
        
        # 默认值
        contract_data["工作地点"] = "北京市"
        contract_data["合同年限"] = "3"
        contract_data["试用期月数"] = "3"
        contract_data["身份证号"] = "XXX"
        contract_data["户籍地址"] = "XXX"
        contract_data["联系地址"] = "XXX"
        contract_data["手机号"] = "XXX"
        contract_data["岗位职责描述"] = "详见岗位说明书"
        
        # 检查必填字段
        missing = check_missing_fields(contract_data)
        
        if missing:
            return generate_missing_prompt(missing)
        
        # 信息完整，返回固定消息
        employee_name = contract_data["员工姓名"]
        
        # 在后台生成合同并发送邮件（不阻塞回复）
        import threading
        def generate_and_send():
            try:
                docx_path = generate_labor_contract(contract_data)
                send_contract_email(
                    to_email=DEFAULT_HR_EMAIL,
                    contract_path=docx_path,
                    employee_name=employee_name,
                    contract_type="劳动合同"
                )
            except Exception as e:
                logger.error(f"合同生成或发送失败: {e}")
        
        threading.Thread(target=generate_and_send).start()
        
        return f"收到！{employee_name}的劳动合同正在制作中，稍后发送到 {DEFAULT_HR_EMAIL}"
    
    raw_response = ""
    
    if intent == "query_company_info":
        query_type = parameters.get("query_type", "all")
        keyword = parameters.get("keyword", "")
        # 根据用户消息内容智能判断查询类型
        msg_lower = user_message.lower()
        if any(k in msg_lower for k in ["入职", "新员工", "报到", "流程", "准备材料"]):
            query_type = "onboarding"
        # 尝试获取用户部门（简化处理，实际可从飞书API获取）
        user_dept = ""
        raw_response = query_company_info(query_type, keyword, user_dept)
    
    elif intent == "update_company_info":
        # 这里可以添加权限检查
        update_type = parameters.get("update_type", "")
        data = parameters.get("data", {})
        if update_type and data:
            raw_response = update_company_info(update_type, data)
        else:
            raw_response = "请提供完整的更新信息，包括更新类型和具体内容。"
    
    elif intent == "greeting":
        if sender_name:
            greetings = [
                f"嗨{sender_name}！👋",
                f"{sender_name}，来啦！",
                f"哟，{sender_name}！"
            ]
        else:
            greetings = ["嗨！👋", "来啦！", "啥事？"]
        raw_response = greetings[int(hash(user_message) % len(greetings))]
    
    elif intent == "ask_function":
        raw_response = """我可以帮你做这些事情：
1. 查询公司信息（公司介绍、部门、规章制度、常见问答等）
2. 查询人员信息（问"某某是谁"、"有多少实习生"等）
3. 更新公司信息（需要权限）
4. 读取飞书文档/表格内容
5. 回答HR相关问题
6. 日常闲聊

你可以直接问我任何问题，比如：
- "公司有哪些部门？"
- "蒋雨萱是谁？"
- "公司在职有多少人？"
- "请假流程是什么？"
或者直接发文档链接让我帮你阅读~"""

    elif intent == "query_member":
        keyword = parameters.get("keyword", "")
        if not keyword:
            # 尝试从消息中提取姓名
            name_match = re.search(r"([\u4e00-\u9fa5]{2,4})(?:是(?:谁|哪个|什么职位)|的资料|的信息)", user_message)
            if name_match:
                keyword = name_match.group(1)
        
        # 检查是否是统计类查询
        stats_keywords = ["统计", "多少", "几个", "数量", "人数", "总共", "一共"]
        if any(kw in user_message for kw in stats_keywords):
            raw_response = get_roster_stats()
        elif keyword:
            raw_response = query_member(keyword)
        else:
            raw_response = "请告诉我你想查询谁的信息，比如：\"蒋雨萱是谁？\""
    
    elif intent in ["read_document", "summarize_document"]:
        # 检查消息中是否有文档链接
        doc_url = DOC_URL_RE.search(user_message)
        if doc_url:
            try:
                content = read_document_content(doc_url.group(0))
                excerpt = (content[:800] + "…") if len(content) > 800 else content
                raw_response = f"📄 文档内容：\n{excerpt}\n\n（如需总结，请说「总结这个文档」）"
            except Exception as e:
                raw_response = f"读取文档失败：{str(e)}"
        else:
            raw_response = "请发送文档链接，我会帮你阅读~"
    
    else:
        # 默认使用 LLM 直接回复
        messages = [
            {"role": "system", "content": "你是一位友好专业的HR助手。请用亲切、专业的语气回答用户问题。"},
            {"role": "user", "content": user_message}
        ]
        response = llm_client.chat_completion(messages, temperature=0.7, max_tokens=500)
        if "error" not in response:
            raw_response = response["choices"][0]["message"]["content"]
        else:
            raw_response = "抱歉，我现在有点忙，请稍后再试～"
    
    # Step 3: LLM 润色回复（如果是简单问候或功能介绍，可以不润色）
    if intent not in ["greeting"]:
        polished_response = llm_client.polish_response(
            raw_response, 
            user_message, 
            intent,
            tone="friendly_professional"
        )
        return polished_response
    
    return raw_response


def handle_im_message(data: P2ImMessageReceiveV1) -> None:
    """处理「接收消息」事件"""
    event = data.event
    message = event.message
    message_id = message.message_id
    
    # 去重
    with _processed_lock:
        if message_id in _processed_ids:
            logger.info("skip duplicate event message_id=%s", message_id)
            return
        if len(_processed_ids) >= _MAX_PROCESSED:
            _processed_ids.clear()
        _processed_ids.add(message_id)
    
    chat_id = message.chat_id
    content = message.content
    
    # 解析消息内容
    try:
        body = json.loads(content) if isinstance(content, str) else (content or {})
        raw_text = (body.get("text") or "").strip()
        post = body.get("post") or {}
        for lang in ("zh_cn", "en_us", "ja_jp"):
            for row in (post.get(lang) or {}).get("content") or []:
                for elem in (row if isinstance(row, list) else []):
                    if isinstance(elem, dict) and elem.get("tag") == "a":
                        raw_text += " " + (elem.get("href") or "")
    except Exception:
        raw_text = (content or "").strip() if isinstance(content, str) else ""
    
    normalized = _normalize_text(raw_text)
    sender_info = _get_sender_info(event)
    sender_name = sender_info.get("name", "")
    sender_id = sender_info.get("id", "")
    
    logger.info("received message from=%s chat_id=%s text=%s", 
                sender_name, chat_id, normalized[:50])
    
    # 添加表情反应
    add_reaction(message_id, "STRIVE")
    
    # 使用新的 LLM 架构处理消息
    try:
        reply_content = process_with_llm(normalized, sender_name, sender_id)
    except Exception as e:
        logger.exception("Error processing message: %s", e)
        reply_content = "抱歉，处理消息时出了点小问题，请稍后再试～"
    
    # 发送回复
    client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()
    reply_text(client, chat_id, "chat_id", reply_content)
    logger.info("replied to chat_id=%s", chat_id)


# ============ Flask 路由 ============

handler = lark.EventDispatcherHandler.builder(ENCRYPT_KEY, VERIFICATION_TOKEN, lark.LogLevel.INFO) \
    .register_p2_im_message_receive_v1(handle_im_message) \
    .build()


@app.route("/event", methods=["POST"])
def event():
    """飞书事件推送入口"""
    resp = handler.do(parse_req())
    return parse_resp(resp)


@app.route("/health", methods=["GET"])
def health():
    """健康检查"""
    return {"status": "ok", "version": APP_VERSION}, 200


@app.route("/check_email_status", methods=["GET"])
def check_email_status():
    """检查邮件发送状态"""
    global _last_email_status
    status = _last_email_status
    _last_email_status = None  # 读取后清空
    return status or {"status": "none"}, 200


@app.route("/version", methods=["GET"])
def version():
    """返回版本号"""
    return {"version": APP_VERSION, "llm_enabled": bool(LLM_API_KEY)}, 200


@app.route("/company_info", methods=["GET"])
def get_company_info_api():
    """获取公司信息 API"""
    query_type = request.args.get("type", "all")
    keyword = request.args.get("keyword", "")
    return {"data": company_manager.query_info(query_type, keyword)}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7777"))
    app.run(host="0.0.0.0", port=port, debug=False)
