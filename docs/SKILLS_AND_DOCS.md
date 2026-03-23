# 功能说明与文档

## 公司信息管理系统

### 数据结构

公司信息存储在 `company_info.json` 中，包含以下模块：

#### 1. 公司基本信息 (`company`)
- 公司名称
- 公司简介
- 公司地址
- 联系方式（电话、邮箱）

#### 2. 部门信息 (`departments`)
- 部门名称
- 部门职能描述
- 部门联系方式

#### 3. 规章制度 (`policies`)
- 制度标题
- 制度内容

#### 4. 常见问题 (`faqs`)
- 问题
- 答案

#### 5. 公告 (`announcements`)
- 公告标题
- 公告内容
- 发布日期

### 查询示例

```
用户：公司有哪些部门？
机器人：我们目前有以下几个部门：
• 人力资源部 - 负责招聘、培训、员工关系等
• 技术部 - 负责产品研发和技术支持
• 财务部 - 负责财务管理和报销审批
```

```
用户：请假流程是什么？
机器人：关于请假流程：
请提前在OA系统提交申请，经直属领导审批通过后方可休假。
```

### 更新示例（管理员）

```
用户：添加一个新FAQ，问公司wifi密码，答请咨询行政部
机器人：✅ 已成功更新 faq 信息！
```

## LLM 架构说明

### 1. 意图识别

使用 LLM 分析用户消息，识别为以下意图之一：
- `query_company_info` - 查询公司信息
- `update_company_info` - 更新公司信息
- `read_document` - 读取文档
- `summarize_document` - 总结文档
- `greeting` - 问候
- `ask_function` - 询问功能
- `other` - 其他

### 2. 工具调用

根据识别的意图，调用相应的工具函数：
- `query_company_info(query_type, keyword)`
- `update_company_info(update_type, data)`
- `get_company_summary()`
- `get_current_time()`
- 文档读取函数

### 3. 回复润色

使用 LLM 将原始回复润色成自然、友好的中文：
- 保持信息准确性
- 语气亲切专业
- 适当使用表情符号
- 结构清晰易读

## 扩展开发

### 添加新工具

在 `app.py` 中使用 `@tool_registry.register` 装饰器注册新工具：

```python
@tool_registry.register(
    name="my_new_tool",
    description="工具描述",
    parameters={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "参数1"}
        },
        "required": ["param1"]
    }
)
def my_new_tool(param1: str) -> str:
    # 实现逻辑
    return f"结果: {param1}"
```

### 添加新意图处理

在 `process_with_llm` 函数中添加新意图的处理逻辑：

```python
elif intent == "my_new_intent":
    # 处理逻辑
    raw_response = "..."
```
