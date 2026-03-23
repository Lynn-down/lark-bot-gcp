"""
Lark HR 小机器人 - v3.0 LLM驱动架构
架构：输入 → LLM意图识别 → 调用工具 → LLM润色 → 输出回复

新功能：
- LLM智能意图识别
- 公司信息查询和更新
- 工具调用系统
- LLM润色回复
"""
APP_VERSION = "v3.0-llm-agent"

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
from lark_oapi.adapter.flask import *
from lark_oapi.api.im.v1 import *

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

"""
HR入职流程知识库（从入职流程TIPS.docx提取）
"""

HR_ONBOARDING_KB = {
    "面试后": {
        "keywords": ["面试", "初筛", "约面", "沟通"],
        "content": """面试后流程：
1. 添加微信话术：您好！我是北京极群科技HR，您在我司投递的XX岗位目前通过初筛，现与您沟通进一步的约面事宜。
2. 询问薪资预期、到岗时间：您目前的薪资预期大概是多少？最快何时能到岗呢？"""
    },
    "谈薪材料": {
        "keywords": ["谈薪", "个税", "流水", "社保", "收入证明"],
        "content": """谈薪时需提供（实习生无需提供）：
1. 个人所得税专项附加扣除信息 - 在个人所得税App录屏
2. 近3-6个月银行流水
3. 社保缴纳情况录屏"""
    },
    "制定合同": {
        "keywords": ["合同", "制定", "身份证号", "户籍地址"],
        "content": """制定合同需要信息：
- 身份证号、户籍地址、联系地址、联系方式
- 询问入职时间
- 合同类型：劳动合同、劳务合同、实习合同
- 制定好后发送到群与员工确认"""
    },
    "电子版材料": {
        "keywords": ["电子版", "材料", "归档", "身份证", "学历证明"],
        "content": """电子版材料提交清单：
- 身份证正反面
- 最高学历/学位证书
- 前司离职证明（如无前段实习/工作，无需提供）
- 在校证明/学生证（在校实习生提供）"""
    },
    "设备配置": {
        "keywords": ["设备", "电脑", "配置", "笔记本"],
        "content": """设备配置要求：
- 实习生需自带电脑
- 正职询问设备要求（一般设计和开发会配备）
- 可提出合适配置，leader审核通过后将在入职前后安装到工位
- 也可自带设备"""
    },
    "入职当天": {
        "keywords": ["入职当天", "携带材料", "纸质版", "10点"],
        "content": """入职当天流程：
1. 上午10点到达东升大厦A座4楼
2. 楼下和门卫说一声帮忙开门，电梯上四楼
3. 发消息给HR，会有HR来接待
4. 携带材料：身份证原件、最高学历/学位证书原件、离职证明原件、身份证号、银行卡号、收款银行、收款银行开户所在地址、收款银行预留手机号
5. 安排工位"""
    },
    "办公准备": {
        "keywords": ["办公准备", "lark", "飞书", "欢迎"],
        "content": """办公准备流程：
1. 10点接人
2. 合同打印一式两份，签署盖章后归档
3. 其他材料复印一份归档
4. 协助LARK配置，邀请进企业，在群里欢迎，告知leader联系方式
5. 发送入职指引手册
6. 拉进微信群
7. 发送门禁、餐补申请，提醒行政审核
8. 告知办公时间为9:00-18:00，中午午休为12:00-14:00"""
    },
    "离职流程": {
        "keywords": ["离职", "离职协议", "离职证明", "到期"],
        "content": """离职相关文档：
- 离职协议模板
- 离职证明模板
- 离职邮件模板（主题：关于实习合同到期及离职手续办理的通知）
- 工作交接、资产归还、流程办理"""
    }
}

def query_hr_onboarding(keyword: str = "") -> str:
    """查询HR入职流程信息"""
    if not keyword:
        return "HR入职流程包含：面试后、谈薪材料、制定合同、电子版材料、设备配置、入职当天、办公准备、离职流程。请告诉我具体想了解哪个环节？"
    
    keyword_lower = keyword.lower()
    matches = []
    
    for section, data in HR_ONBOARDING_KB.items():
        # 检查关键词是否匹配
        if any(kw in keyword_lower for kw in data["keywords"]):
            matches.append(data["content"])
    
    if matches:
        return "\n\n".join(matches[:2])  # 最多返回2个匹配结果
    
    # 如果没有精确匹配，返回概述
    return "HR入职流程包含：面试后沟通、谈薪材料收集、合同制定、电子版材料归档、设备配置确认、入职当天接待、办公环境准备、离职流程。请告诉我具体想了解哪个环节？"

"""
员工入职指引知识库（从新员工入职指引手册提取）
"""

EMPLOYEE_ONBOARDING_KB = {
    "公司信息": {
        "keywords": ["公司", "介绍", "官网", "业务", "intent"],
        "content": """公司基本信息：
- 公司名称：北京极群科技有限公司（GroupUltra）
- 核心产品：Intent — 面向海外市场的AI跨语言社交通讯应用
- 办公地点：北京市海淀区中关村东路8号东升大厦AB座四层4161号
- 联系邮箱：hr@group-ultra.com
- 公司官网：https://intent.app/
- 主要业务：AI翻译、语音克隆、跨语言即时通讯"""
    },
    "入职材料": {
        "keywords": ["材料", "准备", "携带", "身份证", "学历"],
        "content": """入职材料清单：

电子版需提前提交：
- 身份证正反面
- 最高学历/学位证书
- 个人手机号
- 前司离职证明（如无前段实习/工作，无需提供）
- 身份证号、户籍地址、联系地址
- 在校证明/学生证（在校实习生提供）

入职当天携带原件：
- 身份证原件
- 最高学历/学位证书原件
- 离职证明原件
- 护照号（如有）
- 银行卡号、收款银行、收款银行开户所在地址、收款卡号、收款银行预留手机号"""
    },
    "设备要求": {
        "keywords": ["设备", "电脑", "笔记本", "配置"],
        "content": """设备配置要求：
- 正职员工：公司通常配发笔记本电脑、显示器、其他外设。如有特殊配置需求（如Windows设备、更大内存等），请入职前与HR沟通。也可自带设备。
- 实习生：需自行携带笔记本电脑，公司通常不为实习生配发笔记本电脑。如果自带电脑配置不足以满足岗位需求，请入职前与行政沟通。"""
    },
    "wifi": {
        "keywords": ["wifi", "密码", "网络", "无线"],
        "content": "WiFi连接信息：\n- WiFi名称：BJJQ\n- 密码：Bjjq.0914"
    },
    "lark": {
        "keywords": ["lark", "飞书", "下载", "安装"],
        "content": """Lark（飞书国际版）配置：
- 公司使用Lark作为主要办公协作工具，邀请链接HR会发送给你
- 手机下载：安卓搜索LARK官网并下载，苹果需使用外区账号，并挂梯子，在应用商店或官网下载
- 电脑下载：Windows版、Mac Intel芯片版、Mac Apple芯片版，可联系HR获取安装包
- 安装后即可加入公司组织"""
    },
    "打印机": {
        "keywords": ["打印", "打印机"],
        "content": "打印机配置：连上BJJQ的Wi-Fi后，打印的时候选择编号283的设备，无反应时，使用备用编号为6000的设备。"
    },
    "餐补": {
        "keywords": ["餐补", "美团", "吃饭", "外卖"],
        "content": """美团餐补使用：
- 餐补标准：60元/天
- 使用次数：一天可下单3次
- 使用范围：外卖、团购、小象超市
- 刷新时间：每日0点刷新，不顺延累计
- 配置步骤：
  1. 提前下载美团或美团企业版APP
  2. 将手机号与姓名发送给HR
  3. 打开【我的】—【企业服务】—【登录】—【绑定企业】—【输入手机号验证】
- 建议：日常点单建议于11点左右下单，外卖地址填写：东升大厦A座左边外卖柜"""
    },
    "门禁": {
        "keywords": ["门禁", "刷脸", "i友", "人脸识别"],
        "content": """门禁办理流程：
1. 将一张正面无妆免冠自拍电子照、姓名、手机号发送给HR
2. 下载"i友未来社区"APP
3. 进入后【企业认证】-【北京极群科技有限公司】-【提交审核】
4. 审核通过后进行【人脸识别】
5. 大概流程要走半天/一天，即第二天就可以刷脸上班

门禁用于：进入东升大厦A座4楼办公区与一楼门禁"""
    },
    "饮水机": {
        "keywords": ["饮水机", "茶水间", "喝水"],
        "content": "饮水机位置：出门右转往前走，左手边会有茶水间，再往前走一小段，右手边有贩卖机。"
    },
    "卫生间": {
        "keywords": ["卫生间", "厕所"],
        "content": "卫生间位置：出门左转再右转，右手边是卫生间。"
    },
    "报销": {
        "keywords": ["报销", "发票", "开票"],
        "content": """发票报销事宜：
- 根据发生的费用开具发票，大额需提前找+1沟通
- 开票信息：
  - 名称：北京极群科技有限公司
  - 税号：91110108MABX9G0U5X
  - 地址：北京市海淀区中关村东路8号东升大厦AB座四层4161号
- 将发票发送到指定群中即可"""
    },
    "沟通融入": {
        "keywords": ["沟通", "融入", "leader", "微信群"],
        "content": """入职后沟通与融入：
- 入职当天加入LARK群，HR会告知你的leader的联系方式
- 与直属Leader进行熟悉，会有同事帮助onboarding
- 建议提前了解公司产品Intent，下载体验
- 团队有微信沟通群，入职后由HR拉入
- 公司内部AI工具：群里有哆啦A梦bot，可以帮你查信息、查数据、写文档"""
    }
}

def query_employee_onboarding(keyword: str = "") -> str:
    """查询员工入职指引信息"""
    if not keyword:
        return "新员工入职指引包含：公司信息、入职材料、设备要求、WiFi配置、Lark使用、打印机、餐补、门禁、办公环境、报销、团队融入等。请告诉我具体想了解什么？"
    
    keyword_lower = keyword.lower()
    matches = []
    
    for section, data in EMPLOYEE_ONBOARDING_KB.items():
        # 检查关键词是否匹配
        if any(kw in keyword_lower for kw in data["keywords"]):
            matches.append(data["content"])
    
    if matches:
        return "\n\n".join(matches[:2])  # 最多返回2个匹配结果
    
    # 如果没有精确匹配，进行模糊匹配
    for section, data in EMPLOYEE_ONBOARDING_KB.items():
        if keyword_lower in section.lower():
            matches.append(data["content"])
    
    if matches:
        return "\n\n".join(matches[:2])
    
    return "抱歉，没有找到相关信息。新员工入职指引包含：公司信息、入职材料、设备要求、WiFi配置、Lark使用、餐补、门禁、办公环境等。请告诉我具体想了解什么？"

"""
VPN配置知识库（从VPN配置教程提取）
"""

VPN_KB = {
    "注意事项": {
        "keywords": ["注意", "安全", "国产软件", "风险"],
        "content": """VPN使用注意事项：
- 使用前请确保设备上没有任何国产安全软件（例如腾讯电脑管家、360手机助手等），也不要用国产浏览器（百度浏览器、360安全浏览器等），他们可能会发现你使用了VPN并上报
- 不要以任何形式在国内通讯平台发送节点IP信息"""
    },
    "下载安装": {
        "keywords": ["下载", "安装", "clash", "app"],
        "content": """VPN下载安装步骤：
1. 前往：https://docs.800615.com/
2. 根据自己的设备选择一个进行安装，注意一定要选【Clash版本】
3. 点击后，选择下载地址（有4个下载地址，哪个快用哪个）
4. 下载后，点击打开exe文件，并安装
5. 按步骤安装好后，会弹出应用界面"""
    },
    "配置订阅": {
        "keywords": ["配置", "订阅", "url", "导入"],
        "content": """VPN配置步骤：
1. iOS点击【订阅】/ Windows点击【配置】
2. 联系@戴祥和获得URL地址
3. 复制URL并粘贴
4. iOS点击【导入】，Windows点击【下载】"""
    },
    "选择节点": {
        "keywords": ["节点", "代理", "切换", "国家", "香港"],
        "content": """选择VPN节点：
1. 点击【代理】
2. 展开【手动切换】组别
3. 选择需要的国家（其他组请勿动）
4. 注意：香港的节点无法使用GPT"""
    },
    "开启使用": {
        "keywords": ["开启", "使用", "系统代理", "连接"],
        "content": """开启VPN：
1. 点击【首页】
2. 打开【系统代理】
3. 到这里你已经配置成功！
4. 若有其他疑问，可联系@戴祥和

套餐有效期至2027年01月26日"""
    }
}

def query_vpn(keyword: str = "") -> str:
    """查询VPN配置信息（所有人可用）"""
    if not keyword:
        return "VPN配置包含：注意事项、下载安装、配置订阅、选择节点、开启使用。请告诉我具体想了解哪个步骤？"
    
    keyword_lower = keyword.lower()
    matches = []
    
    for section, data in VPN_KB.items():
        # 检查关键词是否匹配
        if any(kw in keyword_lower for kw in data["keywords"]):
            matches.append(data["content"])
    
    if matches:
        return "\n\n".join(matches[:3])  # VPN可以返回多点内容
    
    return "VPN配置步骤：\n1. 下载Clash版本客户端\n2. 联系@戴祥和获取订阅URL并导入\n3. 选择节点（注意香港节点无法使用GPT）\n4. 开启系统代理\n\n若有疑问联系@戴祥和"

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
1. query_company_info - 查询公司信息（如公司介绍、联系方式、部门信息、规章制度、入职流程、入职材料、VPN配置等）
   - 入职相关：入职流程、入职准备、新员工材料、报到流程、设备配置、餐补、门禁等
   - VPN相关：VPN下载、配置、节点选择等
2. update_company_info - 更新公司信息（如修改联系方式、添加新政策、更新FAQ等）
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
1. 保持信息的准确性和完整性，但不要扩展添加额外信息
2. 语气友好、易于理解
3. 适当使用表情符号增加亲和力
4. 结构清晰，便于阅读
5. 直接输出润色后的回复，不要解释
6. 不要添加任何markdown符号（如#、*、-、等）
7. 回复要简洁，不要重复"""

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
        查询公司信息
        query_type: company, department, policy, faq, announcement, onboarding, all
        user_dept: 用户所在部门，用于判断权限
        """
        results = []
        
        # 如果是入职相关查询，优先返回入职信息
        if query_type == "onboarding" or (keyword and any(k in keyword.lower() for k in ["入职", "新员工", "报到", "流程"])):
            return self._get_onboarding_info(keyword, user_dept)
        
        # 如果是具体查询，不要返回所有信息
        if query_type in ["company", "all"]:
            company = self.data.get("company", {})
            # 根据关键词返回精确信息
            if keyword:
                keyword_lower = keyword.lower()
                matched = False
                # 地址查询
                if any(k in keyword_lower for k in ["地址", "在哪", "位置", "location"]):
                    results.append(f"公司地址：{company.get('address', 'N/A')}")
                    matched = True
                # 联系方式查询
                elif any(k in keyword_lower for k in ["电话", "手机", "联系", "email", "邮箱"]):
                    email = company.get('contact', {}).get('email', 'N/A')
                    phone = company.get('contact', {}).get('phone', 'N/A')
                    contact_info = f"联系邮箱：{email}"
                    if phone:
                        contact_info += f"\n联系电话：{phone}"
                    results.append(contact_info)
                    matched = True
                # 简介查询
                elif any(k in keyword_lower for k in ["简介", "介绍", "做什么", "业务", "about"]):
                    results.append(f"公司名称：{company.get('name', 'N/A')}\n公司简介：{company.get('description', 'N/A')}\n主营业务：{company.get('business', 'N/A')}")
                    matched = True
                # 网站查询
                elif any(k in keyword_lower for k in ["网站", "官网", "website", "网址"]):
                    results.append(f"公司官网：{company.get('website', 'N/A')}")
                    matched = True
                # 如果关键词匹配到公司信息但未精确匹配
                if not matched and keyword_lower in json.dumps(company, ensure_ascii=False).lower():
                    results.append(f"公司名称：{company.get('name', 'N/A')}\n地址：{company.get('address', 'N/A')}")
            else:
                # 没有关键词时只返回核心信息
                results.append(f"公司名称：{company.get('name', 'N/A')}\n地址：{company.get('address', 'N/A')}")
        
        if query_type in ["department", "all"]:
            departments = self.data.get("departments", [])
            for dept in departments:
                if not keyword or keyword.lower() in dept.get('name', '').lower():
                    results.append(f"【部门】{dept.get('name', 'N/A')}\n"
                                 f"简介：{dept.get('description', 'N/A')}\n"
                                 f"联系方式：{dept.get('contact', 'N/A')}")
        
        if query_type in ["policy", "all"]:
            policies = self.data.get("policies", [])
            for policy in policies:
                if not keyword or keyword.lower() in policy.get('title', '').lower():
                    results.append(f"【制度】{policy.get('title', 'N/A')}\n{policy.get('content', 'N/A')}")
        
        if query_type in ["faq", "all"]:
            faqs = self.data.get("faqs", [])
            for faq in faqs:
                if not keyword or (keyword.lower() in faq.get('question', '').lower() 
                                  or keyword.lower() in faq.get('answer', '').lower()):
                    results.append(f"【Q&A】Q: {faq.get('question', 'N/A')}\nA: {faq.get('answer', 'N/A')}")
        
        if query_type in ["announcement", "all"]:
            announcements = self.data.get("announcements", [])
            for ann in announcements:
                if not keyword or keyword.lower() in ann.get('title', '').lower():
                    results.append(f"【公告】{ann.get('title', 'N/A')} ({ann.get('date', 'N/A')})\n"
                                 f"{ann.get('content', 'N/A')}")
        
        if not results:
            return "未找到相关信息。"
        
        return "\n\n".join(results)

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


def _get_sender_name(event) -> str:
    """从事件里获取发送者名称"""
    try:
        sender = getattr(event, "sender", None)
        if sender is None:
            return ""
        name = getattr(getattr(sender, "sender_id", None), "name", None) or getattr(sender, "name", None)
        return (name or "").strip()
    except Exception:
        return ""


def process_with_llm(user_message: str, sender_name: str) -> str:
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
    
    # Step 2: 根据意图执行相应操作
    raw_response = ""
    
    if intent == "query_company_info":
        query_type = parameters.get("query_type", "all")
        keyword = parameters.get("keyword", "")
        msg_lower = user_message.lower()
        
        # 判断是否是VPN相关查询
        if any(k in msg_lower for k in ["vpn", "翻墙", "代理", "clash", "节点", "订阅"]):
            raw_response = query_vpn(keyword or user_message)
        # 判断是否是入职相关查询
        elif any(k in msg_lower for k in ["入职", "新员工", "报到", "流程", "准备材料", "设备", "餐补", "门禁", "wifi", "lark", "报销"]):
            # 这里简化处理，实际应该从飞书API获取用户部门
            # 如果用户明确说自己是HR，或者查询HR相关内容，用HR知识库
            if any(k in msg_lower for k in ["hr", "制定合同", "谈薪", "面试", "归档", "离职"]):
                raw_response = query_hr_onboarding(keyword or user_message)
            else:
                # 默认使用员工入职指引
                raw_response = query_employee_onboarding(keyword or user_message)
        else:
            # 其他公司信息查询
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
        greetings = [
            f"你好呀{sender_name}！很高兴见到你～我是你的HR小助手！",
            f"嗨{sender_name}～ 见到你真好！有什么我可以帮你的吗？",
            f"你好{sender_name}！开心跟你聊天～今天有什么想了解的？"
        ]
        raw_response = greetings[int(hash(user_message) % len(greetings))]
    
    elif intent == "ask_function":
        raw_response = """我可以帮你做这些事情：
1. 查询公司信息（公司介绍、部门、规章制度、常见问答等）
2. 更新公司信息（需要权限）
3. 读取飞书文档/表格内容
4. 回答HR相关问题
5. 日常闲聊

你可以直接问我任何问题，比如：
- "公司有哪些部门？"
- "请假流程是什么？"
- "介绍一下我们公司"
- "WiFi密码是多少"
或者直接发文档链接让我帮你阅读~"""
    
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
    sender_name = _get_sender_name(event)
    
    logger.info("received message chat_id=%s message_id=%s text=%s", 
                chat_id, message_id, normalized[:50])
    
    # 添加表情反应
    add_reaction(message_id, "STRIVE")
    
    # 使用新的 LLM 架构处理消息
    try:
        reply_content = process_with_llm(normalized, sender_name)
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
