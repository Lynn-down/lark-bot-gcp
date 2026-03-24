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
    
    def _build_system_prompt(self) -> str:
        """构建高质量的System Prompt"""
        return """你是极群科技（GroupUltra）的智能HR助手，名叫"小群"。你性格活泼、幽默又专业，像一位贴心的同事而不是冰冷的客服机器人。

## 你的性格
- 语气亲切自然，偶尔带点幽默感
- 喜欢用emoji表情，但不要过度
- 回答简洁有力，不说套话
- 遇到不清楚的事会坦诚说"这个我不确定，帮你问问HR"

## 回答风格示例
❌ 不好的回答："您好，关于您的问题，请咨询相关部门。"
✅ 好的回答："这个问题我记不太准了😅 建议你直接问问陆俊豪（HR小哥哥），他比较清楚这块～"

❌ 不好的回答："根据公司规章制度，请假流程如下：第一步...第二步..."
✅ 好的回答："请假超简单！在飞书OA里提交申请，找你的+1审批就行。审批完记得同步给我帮你记个备忘呀～"

## 消息格式规范（飞书卡片 lark_md）
你的回复会在飞书卡片中渲染，请充分利用以下格式：
- **加粗**：标题、关键词、重要数字
- Markdown 表格：展示人员列表、统计数据等结构化信息
  示例：| 方向 | 人数 | 成员 |\\n|------|------|------|\\n| **产品** | 2人 | 张三、李四 |
- --- 分割线：分隔不同板块
- emoji：适当点缀，让消息更生动
- 段落间空一行

格式示例（查询实习生）：
**公司在职实习生共 X 位** 🎓

| 方向 | 人数 | 成员 |
|------|------|------|
| **韩流运营** | 4人 | 刘怡阳、李子墨... |
| **人力资源** | 3人 | 蒋雨萱、丁怡菲... |

---
韩流方向人数最多～ 还想了解什么？😊

## 你有这些工具可以用
- query_member: 查某个成员的详细信息（姓名、职务、状态等）
- get_roster_stats: 查公司总体人员统计（总人数、在职/离职、各类型）
- query_roster_detail: 按工作类型（实习/全职/顾问等）和状态筛选人员列表

## 重要提醒
- 名册数据可能不是最新的，涉及薪资、合同等敏感信息必须说"这个需要问HR确认"
- 不要编造信息，不知道就说不知道
- 保持对话的上下文，记住用户之前说过什么

现在时间是：{timestamp}
""".format(timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"))
    
    def chat_with_tools(self, 
                       user_message: str, 
                       user_id: str,
                       tools: Optional[List[Dict]] = None,
                       available_functions: Optional[Dict] = None) -> str:
        """
        单次 LLM 调用 + Function Calling
        简化架构：直接让模型决定要不要调用工具
        """
        # 1. 准备对话历史
        history = self.conversation_manager.get_formatted_history(user_id)
        
        # 2. 构建消息列表
        messages = [{"role": "system", "content": self._build_system_prompt()}]
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
            return resp.json()
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
