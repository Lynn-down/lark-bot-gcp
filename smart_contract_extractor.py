#!/usr/bin/env python3
"""
智能合同字段提取器 - 从自然语言消息中提取合同信息
"""
import re
from typing import Dict, List, Tuple

# 字段别名映射 - 支持多种说法
FIELD_ALIASES = {
    "员工姓名": ["姓名", "名字", "员工", "人名", "叫", "是谁"],
    "身份证号": ["身份证", "证件号", "身份号"],
    "户籍地址": ["户籍", "户口", "籍贯地址"],
    "联系地址": ["地址", "住址", "现住址", "居住地址", "住哪"],
    "手机号": ["手机", "电话", "联系方式", "号码"],
    "岗位名称": ["岗位", "职位", "职务", "title", "做什么", "工种"],
    "税前工资": ["工资", "薪资", "薪水", "报酬", "月薪", "给多少钱"],
    "工作地点": ["地点", "工作地", "办公地点", "base", "在哪上班"],
    "签订日期": ["签订", "签约", "日期", "开始", "入职时间", "入职日期"],
    "合同年限": ["年限", "几年", "签几年", "期限"],
    "试用期月数": ["试用期", "试几个月"],
    "岗位职责描述": ["职责", "工作内容", "要做什么", "职位描述", "JD", "job description"],
}

# 必填字段
REQUIRED_FIELDS = ["员工姓名", "岗位名称", "税前工资"]

# 默认HR邮箱
DEFAULT_HR_EMAIL = "18924538056@163.com"


def extract_contract_info(message: str) -> Tuple[Dict[str, str], List[str]]:
    """
    从消息中提取合同信息
    
    Returns:
        (提取的数据, 缺失的必填字段列表)
    """
    data = {}
    message_lower = message.lower()
    
    # 1. 提取合同类型
    if "劳动" in message:
        data["合同类型"] = "劳动"
    elif "劳务" in message:
        data["合同类型"] = "劳务"
    elif "实习" in message:
        data["合同类型"] = "实习"
    else:
        data["合同类型"] = "劳动"  # 默认
    
    # 2. 使用正则表达式提取字段
    # 姓名提取 - 更灵活的模式
    name_patterns = [
        r"(?:姓名|名字|员工|叫|是谁)[是:：]?\s*([\u4e00-\u9fa5]{2,4})",
        r"([\u4e00-\u9fa5]{2,4})的?(?:合同|入职)",
        r"做一份.*?(?:给|帮)?([\u4e00-\u9fa5]{2,4})的",
    ]
    for pattern in name_patterns:
        match = re.search(pattern, message)
        if match:
            data["员工姓名"] = match.group(1).strip()
            break
    
    # 岗位提取
    position_patterns = [
        r"(?:岗位|职位|职务|title|做什么)[是:：]?\s*([\u4e00-\u9fa5a-zA-Z]{2,20})",
        r"(?:招|做|当|担任)([\u4e00-\u9fa5a-zA-Z]{2,20})(?:实习生|专员|经理|主管|助理)?",
    ]
    for pattern in position_patterns:
        match = re.search(pattern, message)
        if match and "岗位名称" not in data:
            pos = match.group(1).strip()
            # 排除常见的非岗位词
            if pos not in ["合同", "文件", "文档"]:
                data["岗位名称"] = pos
                break
    
    # 工资提取 - 支持多种格式
    salary_patterns = [
        r"(?:工资|薪资|薪水|报酬|月薪)[是:：]?\s*(\d+)(?:\s*元?/?月?)?",
        r"(\d+)(?:\s*元?/?月?)(?:\s*工资|薪资|薪水)?",
        r"给(\d+)(?:\s*元)",
    ]
    for pattern in salary_patterns:
        match = re.search(pattern, message)
        if match:
            data["税前工资"] = match.group(1).strip()
            break
    
    # 身份证号提取
    idcard_match = re.search(r"(\d{15}|\d{18}|\d{17}[Xx])", message.replace(" ", ""))
    if idcard_match:
        data["身份证号"] = idcard_match.group(1)
    
    # 手机号提取
    phone_match = re.search(r"(1[3-9]\d{9})", message)
    if phone_match:
        data["手机号"] = phone_match.group(1)
    
    # 日期提取 - 支持多种格式
    date_patterns = [
        r"(\d{4})年(\d{1,2})月(\d{1,2})日",
        r"(\d{4})-(\d{1,2})-(\d{1,2})",
        r"(\d{4})/(\d{1,2})/(\d{1,2})",
    ]
    for pattern in date_patterns:
        match = re.search(pattern, message)
        if match:
            year, month, day = match.groups()
            data["签订日期"] = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            break
    
    # 试用期提取
    probation_match = re.search(r"试用期[:：]?\s*(\d+)\s*个月?", message)
    if probation_match:
        data["试用期月数"] = probation_match.group(1)
    
    # 年限提取
    year_match = re.search(r"(?:签|合同)?[:：]?\s*(\d+)\s*年", message)
    if year_match:
        data["合同年限"] = year_match.group(1)
    
    # 3. 检查缺失的必填字段
    missing = []
    for field in REQUIRED_FIELDS:
        if field not in data or not data[field]:
            missing.append(field)
    
    # 4. 设置默认值
    defaults = {
        "工作地点": "北京市",
        "试用期月数": "3",
        "合同年限": "3",
        "签订日期": None,  # 使用当天
    }
    for key, value in defaults.items():
        if key not in data or not data[key]:
            if key == "签订日期":
                from datetime import datetime
                data[key] = datetime.now().strftime("%Y-%m-%d")
            else:
                data[key] = value
    
    # 5. 处理XXX占位符
    xxx_fields = ["身份证号", "户籍地址", "联系地址", "手机号"]
    for field in xxx_fields:
        if field not in data:
            data[field] = "XXX"
    
    return data, missing


def generate_missing_fields_prompt(missing_fields: List[str]) -> str:
    """
    生成追问消息
    """
    field_hints = {
        "员工姓名": "员工叫什么名字？",
        "岗位名称": "是什么岗位？（比如：产品经理、前端开发等）",
        "税前工资": "月薪是多少？",
    }
    
    prompts = [field_hints.get(f, f"请提供{f}") for f in missing_fields]
    
    return "信息还缺一点哦：\\n" + "\\n".join([f"• {p}" for p in prompts])


def parse_natural_language(message: str) -> Dict:
    """
    解析自然语言消息，返回完整的合同生成指令
    """
    data, missing = extract_contract_info(message)
    
    result = {
        "data": data,
        "missing": missing,
        "is_complete": len(missing) == 0,
        "prompt": None if len(missing) == 0 else generate_missing_fields_prompt(missing)
    }
    
    return result


if __name__ == "__main__":
    # 测试
    test_messages = [
        "做一份劳动合同，姓名是张三，岗位是人事实习生，工资20000",
        "帮李四生成劳务合同，前端开发，月薪15000",
        "王五要入职，产品经理，25000一个月",
    ]
    
    for msg in test_messages:
        print(f"\n消息: {msg}")
        result = parse_natural_language(msg)
        print(f"提取数据: {result['data']}")
        print(f"缺失字段: {result['missing']}")
        print(f"完整: {result['is_complete']}")
