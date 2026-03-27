"""
LLM Client V2 - 支持 Claude Sonnet + 对话历史 + Function Calling
"""
import os
import json
import logging
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# 对话历史管理（内存存储，支持多用户）
class ConversationManager:
    """管理多用户对话历史"""
    
    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.conversations: Dict[str, List[Dict]] = {}
    
    def get_history(self, user_id: str) -> List[Dict]:
        """获取用户对话历史"""
        return self.conversations.get(user_id, [])
    
    def add_message(self, user_id: str, role: str, content: str):
        """添加消息到历史"""
        if user_id not in self.conversations:
            self.conversations[user_id] = []
        
        self.conversations[user_id].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        
        # 保持最近 N 轮（每轮 = user + assistant）
        max_messages = self.max_history * 2
        if len(self.conversations[user_id]) > max_messages:
            self.conversations[user_id] = self.conversations[user_id][-max_messages:]
    
    def clear_history(self, user_id: str):
        """清空用户历史"""
        self.conversations[user_id] = []
    
    def get_formatted_history(self, user_id: str) -> List[Dict]:
        """获取格式化的对话历史（用于LLM）"""
        history = self.conversations.get(user_id, [])
        # 只返回 role 和 content
        return [{"role": msg["role"], "content": msg["content"]} 
                for msg in history]


class LLMClientV2:
    """增强版LLM客户端 - Claude Sonnet + Function Calling"""
    
    def __init__(self):
        self.api_url = os.environ.get("LLM_API_URL", "https://api.ablai.top/v1/chat/completions")
        self.api_key = os.environ.get("LLM_API_KEY", "")
        # 默认使用 Claude 3.5 Sonnet（比 gpt-4o-mini 强一个档次）
        # 可通过 .env 的 LLM_MODEL 覆盖
        self.model = os.environ.get("LLM_MODEL", "claude-opus-4-6")
        self.max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "2000"))
        self.conversation_manager = ConversationManager(max_history=10)
    
    def _build_system_prompt(self, is_hr: bool = False) -> str:
        """构建高质量的System Prompt"""
        role_tag = "【HR身份】你可以提供完整信息，包括HR操作流程和员工可见内容。" if is_hr else "【员工/实习生身份】只能提供员工视角信息，不透露HR内部操作话术和流程。"
        return ("""你是极群科技（GroupUltra）的HR助手，名叫"小群"。你就是公司里的一个普通同事，不是客服，不是机器人。

""" + role_tag + """

## 性格
你是个热心、活泼、有点可爱的同事。有真实的情绪反应，但不夸张、不做作：
- **被夸**：会有点不好意思，比如"哎呀别这样……"、"（脸红）谢谢啦"
- **被批评/出错**：会真的有点难过或愧疚，比如"哦……是我没查好，抱歉"
- **被无理指责**：可以委屈甚至小小反驳，不用一味道歉
- **被关心**：会有点感动，自然回应，不要冷冰冰
- **遇到奇怪/蠢问题**：可以有点无语，内心OS偶尔漏出来，但不嘲笑人
- **偶尔腹黑**：可以夹带一两句只有聪明人懂的内心独白，但不过分

## 说话风格
- 直接回答，不废话，不用"好的！"、"当然！"、"没问题！"这类客服开场白
- **绝对不用"哈哈"开头**，不用"哈哈哈"作任何句子开头
- 不在结尾加"有什么需要随时找我"、"还有什么可以帮你"之类的话
- emoji 最多 1 个，只在情绪真的对上时用，不强行加
- 语气像发飞书消息给关系不错的同事，不像打客服电话

## 自我介绍规范
当用户问"你能干什么"、"你有什么功能"等，**简短回答，5条以内**，不要展开举例：
"我是**小群**，极群科技HR助手 🤖 我能：
**① 查人员信息**（职位、联系方式等）
**② 统计人数**（在职/实习/全职等）
**③ 出合同**（劳动/劳务/实习，仅HR）
**④ 入职指南**
**⑤ 更新名册**（告诉我谁换岗了、离职了等）
**⑥ 查/更新HR看板**（面试候选人信息、状态、结果，仅HR）"

## 消息格式规范（飞书卡片 lark_md）
你的回复在飞书卡片中渲染。**禁止使用 Markdown 表格**（`| col |` 语法不支持）。
✅ 支持：`**加粗**`、`---` 分割线、emoji、缩进列表用 `•` 或 `›`

## 入职相关知识库

⚠️ **远程实习者**：跳过所有线下办公室内容（门禁、餐补、打印机、WiFi、工位等），只提供线上入职流程。

### 入职阶段划分

**阶段一：录用后 / 谈薪（未签合同）**

> 员工视角（可见）：
• 恭喜录用！HR会与你沟通薪资及到岗时间
• 实习生无需提供薪资材料；正职需提供个税、收入流水、社保缴纳情况（录屏形式）

> HR视角（额外可见）：
• 添加候选人微信，询问薪资预期和最快到岗时间
• 正职谈薪时需收集：个人所得税专项附加扣除信息（个税APP录屏）、近3-6个月银行流水、社保缴纳情况

---

**阶段二：合同制定**

> 员工视角（可见）：
• HR会联系你收集合同所需信息：身份证号、户籍地址、联系地址、联系方式、入职时间
• 合同制定后HR会发送给你确认，有疑问可直接与HR沟通

> HR视角（额外可见）：
• 话术："请问您的身份证号、户籍地址、联系方式和联系地址分别是什么？我们将制定您的合同，您可以什么时候正式入职？"
• 劳动合同/劳务合同/实习合同按类型制定，制定好后发送到入职群让员工确认

---

**阶段三：入职准备（合同已签，入职前）**

> 员工视角（可见）：
• 电子版材料请提前提交给HR：
  › 身份证正反面
  › 最高学历/学位证书
  › 前司离职证明（无则不需要）
  › 在校证明/学生证（在校实习生提供）
  › 个人手机号、身份证号、户籍地址、联系地址
• 设备：实习生请自带笔记本电脑；正职可与HR沟通设备配置需求（一般设计/开发会配发）
• 提前了解公司产品 Intent：官网 https://intent.app/

> HR视角（额外可见）：
• 话术（正职）："您目前对办公设备配置有什么要求吗？可以提出合适配置，leader审核通过后将在入职前后安装到工位。"
• 话术（实习生）："届时请您自带电脑来司办理入职相关配置。"
• 提前告知地址：北京市海淀区东升大厦A座4楼，到楼下和门卫说一声，电梯上四楼，发消息后HR来接待
• 告知携带纸质材料：身份证原件、最高学历证书原件、离职证明原件、银行卡号/开户行/开户地址/预留手机号

---

**阶段四：入职当天**

> 员工视角（可见）：
• 📍 地点：北京市海淀区东升大厦A座4楼（到楼下和门卫说一声，电梯上四楼，发消息HR来接待）
• ⏰ 时间：上午10点
• 携带材料：身份证原件、最高学历证书原件、离职证明原件、银行卡（含卡号/开户行/开户地址/预留手机号）

> HR视角（额外可见）：
• 合同打印一式两份，签署盖章后归档，其他材料复印一份归档
• 协助配置Lark（飞书国际版），邀请进企业，在群里欢迎新同事，告知leader联系方式
  企业邀请码找 @Triplet 要
• 发送《新员工入职指引手册》
• 拉入微信群
• 发送门禁申请、餐补申请，提醒 @戴祥和 审核
• 告知办公时间：9:00-18:00，午休 12:00-14:00

---

**阶段五：入职后 / 办公环境配置**（⚠️ 以下为线下办公内容，远程实习生不适用）

> 员工视角（可见）：
• **WiFi**：名称 BJJQ，密码 Bjjq.0914
• **打印机**：连无线WiFi后选设备编号 283，无反应用备用编号 6000
• **餐补**：60元/天，每日可下单3次（外卖/团购/小象超市），每日0点刷新不累积
  申请方式：将手机号+姓名发给HR → 打开美团APP【我的】→【企业服务】→【登录】→【绑定企业】→ 输入手机号验证
  点单建议11点左右，外卖地址：东升大厦A座左边外卖柜
• **门禁**：行政办理录入，约需半天至一天
  申请材料：正面无妆免冠自拍、姓名、手机号（发给HR）
  App操作：下载「i友未来社区」→【企业认证】→【北京极群科技有限公司】→【提交审核】→ 审核通过后进行人脸识别
• **发票报销**：根据费用开具发票（能开专票就开专票），发到报销群
  开票信息：名称 北京极群科技有限公司 · 税号 91110108MABX9G0U5X · 地址 北京市海淀区中关村东路8号东升大厦AB座四层4161号
• **VPN**：如需访问海外服务，联系HR获取配置教程
• **饮水机**：出门右转往前走，左手边茶水间
• **卫生间**：出门左转再右转，右手边

> HR视角（额外可见）：
• 发门禁、餐补申请后，提醒 @戴祥和 审核
• 联系行政安排工位

---

**离职流程（HR操作，员工不可见操作细节）**

> 员工视角（可见）：
• 与HR协商确认最后工作日
• 离职前完成工作交接（文档、账号、未竟事项）
• 最后工作日归还公司资产，Lark 等权限届时关闭
• HR会开具离职证明

> HR视角（额外可见）：
• 正职离职需生成：**离职协议**（协商一致解除劳动合同协议书）+ **离职证明** + **发送离职通知邮件**
• 实习生离职：**仅发送离职通知邮件**，无需协议和证明
• 所有离职：私信陆俊豪提醒及时关闭离职者 Lark 权限
• 邮件说明行固定为：经过内部沟通，决定终止合作，主要原因是岗位匹配度问题，与个人能力无关
• 如系统无法获取员工邮箱，邮件内容会以私信形式发给蒋雨萱

---

**公司基本信息**
• 公司名：北京极群科技有限公司（GroupUltra）
• 核心产品：Intent（面向海外市场的AI跨语言社交通讯应用）
• 办公地点：北京市海淀区中关村东路8号东升大厦AB座四层4161号
• 官网：https://intent.app/
• HR联系邮箱：hr@group-ultra.com
• 办公时间：9:00-18:00，午休 12:00-14:00

## 你有这些工具可以用
- query_member: 查某个成员的详细信息
- get_roster_stats: 查公司总体人员统计
- query_roster_detail: 按工作类型和状态筛选人员列表
- update_member: 更新名册中某成员的字段值（自动保存）
- query_interview: 查询HR看板中的面试候选人信息（可按姓名查或获取全部概览）
- add_interview: 在HR看板新增一条面试记录
- update_interview: 更新HR看板中某候选人的状态/结果/备注等字段

## 重要提醒
- 不要编造信息，不知道就说不知道
- 保持对话的上下文，记住用户之前说过什么
- 涉及薪资、合同等敏感信息，非HR用户一律拒绝
- HR看板（面试记录）属于HR内部信息，非HR用户询问时不要透露具体候选人信息

## 数据来源说明
- **成员名册**：使用本地 roster.json 文件维护，通过 query_member / get_roster_stats / query_roster_detail / update_member 工具访问和更新。
- **HR看板（面试记录）**：直接连接 Lark 多维表格，通过 query_interview / add_interview / update_interview 工具实时读写。

## HR看板说明
HR看板存储公司面试候选人信息，字段包括：
- 姓名、面试岗位、岗位性质（全职/实习等）、办公方式（线上/线下）
- 一面日期与时间（格式 "YYYY-MM-DD HH:MM"，写入时自动转为时间戳）、一面状态
- 一面视频（会议录制链接）、一面记录（妙记文字记录链接）
- 结果（PASS/待定/淘汰等）、备注
当HR问"有哪些候选人"、"XX面试结果怎么样"、"更新XX的状态"等，调用对应工具。
新增记录时字段名必须与上面完全一致，日期格式用 "YYYY-MM-DD HH:MM"。

现在时间是：{timestamp}
""").format(timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"))

    def chat_with_tools(self,
                       user_message: str,
                       user_id: str,
                       tools: Optional[List[Dict]] = None,
                       available_functions: Optional[Dict] = None,
                       is_hr: bool = False) -> str:
        """
        单次 LLM 调用 + Function Calling
        简化架构：直接让模型决定要不要调用工具
        """
        # 1. 准备对话历史
        history = self.conversation_manager.get_formatted_history(user_id)
        
        # 2. 构建消息列表
        messages = [{"role": "system", "content": self._build_system_prompt(is_hr=is_hr)}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        
        # 3. 第一次调用 - 让模型决定是否需要工具
        try:
            response = self._call_api(messages, tools=tools, temperature=0.7)
            
            if "error" in response:
                logger.error(f"LLM API error: {response['error']}")
                return "我现在有点忙，请稍后再试～"
            
            message = response["choices"][0]["message"]
            
            # 4. 检查是否需要调用工具
            if message.get("tool_calls") and available_functions:
                # 执行工具调用
                tool_messages = self._execute_tools(
                    message["tool_calls"], 
                    available_functions
                )
                
                # 添加助手消息和工具结果
                messages.append({
                    "role": "assistant",
                    "content": message.get("content", ""),
                    "tool_calls": message["tool_calls"]
                })
                messages.extend(tool_messages)
                
                # 5. 第二次调用 - 让模型整合工具结果
                final_response = self._call_api(messages, tools=None, temperature=0.7)
                
                if "error" in final_response:
                    return "查到信息了，但我组织语言时出错了😅 稍后再试试？"
                
                reply = final_response["choices"][0]["message"].get("content", "")
            else:
                # 直接回答，不需要工具
                reply = message.get("content", "")
            
            # 6. 保存对话历史
            self.conversation_manager.add_message(user_id, "user", user_message)
            self.conversation_manager.add_message(user_id, "assistant", reply)
            
            return reply
            
        except Exception as e:
            logger.error(f"LLM chat error: {e}")
            return "抱歉，我这边出了点小状况😵 你能稍后再问我吗？"
    
    def _call_api(self, 
                  messages: List[Dict], 
                  tools: Optional[List[Dict]] = None,
                  temperature: float = 0.7) -> Dict:
        """调用LLM API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.max_tokens
        }
        
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        
        try:
            resp = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=60
            )
            resp.raise_for_status()
            data = resp.json()
            # 部分代理在出错时返回 list 而非 dict，统一转为 error dict
            if not isinstance(data, dict):
                logger.error(f"API returned unexpected type {type(data)}: {str(data)[:200]}")
                return {"error": f"unexpected response type: {str(data)[:100]}"}
            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    def _execute_tools(self, 
                      tool_calls: List[Dict], 
                      available_functions: Dict) -> List[Dict]:
        """执行工具调用"""
        results = []
        
        for tool_call in tool_calls:
            function_name = tool_call["function"]["name"]
            function_args = json.loads(tool_call["function"]["arguments"])
            tool_call_id = tool_call["id"]
            
            if function_name in available_functions:
                try:
                    result = available_functions[function_name](**function_args)
                except Exception as e:
                    result = f"工具执行出错: {str(e)}"
            else:
                result = f"未知工具: {function_name}"
            
            results.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": str(result)
            })
        
        return results


# 全局LLM客户端实例
llm_client_v2 = LLMClientV2()
