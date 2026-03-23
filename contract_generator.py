#!/usr/bin/env python3
"""
合同生成器 - 根据模板和用户信息生成合同
"""

# 劳动合同模板（带XX占位符）
LABOR_CONTRACT_TEMPLATE = """劳动合同（通用）

甲    方：北京极群科技有限公司
乙    方：XX员工姓名XX
签订日期：  XX签订年份XX  年  XX签订月份XX  月  XX签订日期XX  日

劳动合同

本劳动合同（下称"本合同"）由以下双方于  XX签订年份XX  年  XX签订月份XX 月  XX签订日期XX  日签订：

甲方：
注册地址：北京市海淀区中关村东路8号东升大厦AB座四层4161号
法定代表人：陈春宇

乙方：
身份证号码：XX身份证号XX
户籍地址：XX户籍地址XX
联系地址：XX联系地址XX
联系电话：XX手机号XX

鉴于：
甲方已如实告知并经乙方确认其工作内容、工作条件、工作地点、职业危害、安全生产状况、劳动报酬以及乙方要求了解的其他情况；
根据《中华人民共和国劳动法》《中华人民共和国劳动合同法》等法律法规政策规定,甲乙双方遵循合法、公平、平等自愿、协商一致、诚实信用的原则订立本合同，共同遵守所列条款。

合同期限
1.  本合同为（任选一种）：
（1）□无固定期限合同；
（2）☑有固定期限，合同期限  XX合同年限XX  年，自  XX签订年份XX  年 XX签订月份XX 月 XX签订日期XX  日起至  XX结束年份XX  年 XX结束月份XX 月 XX结束日期XX  日止，试用期为 XX试用期月数XX 个月；
（3）□以完成一定工作任务为期限。

2.  本合同到期后，甲方未提出续签或乙方不同意续签的，本合同到期终止。

工作内容、工作地点
1.  乙方工作地点为     XX工作地点XX      。

2.  签订合同时，乙方工作岗位为  XX岗位名称XX   ，基本岗位职责详见附件1：基本岗位职责描述。

3.  乙方应当接受甲方对其进行的工作岗位所必需的培训。

4.  乙方必须按照甲方确定的岗位职责，按时、按质、按量完成工作。

工作时间和休息休假
1.  甲方安排乙方执行标准工时工作制。每日工作时间8小时，每周工作时间40小时，每周至少休息一日。

2.  甲方安排乙方加班的，应依法优先安排补休，无法安排补休的依法支付加班工资。

3.  乙方依法享有国家规定的各种法定节假日和甲方的休假待遇。

四、劳动报酬
1.  甲方依法制定工资分配制度，并告知乙方。甲方至少每月以货币形式向乙方支付一次工资。甲方经与乙方协商，约定按照如下方式向乙方以货币形式发放工资，于每月15日前足额支付：
固定工资 XX税前工资XX 元/月（税前）。

2.  试用期内，乙方的工资为转正后的  100  %。

3.  双方按照国家和地方规定缴纳社会保险和住房公积金。

五、劳动纪律
1.  乙方应遵守国家的法律法规。

2.  乙方已知悉并详细阅读甲方的各项规章制度，并承诺严格遵守。

3.  [其他劳动纪律条款保持不变]

附件1：基本岗位职责描述
XX岗位职责描述XX
"""

# 劳务合同模板
SERVICE_CONTRACT_TEMPLATE = """劳务合同

本劳务合同（下称"本合同"）由以下双方于  XX签订年份XX  年  XX签订月份XX  月  XX签订日期XX  日签订：

甲方：
注册地址：北京市海淀区中关村东路8号东升大厦AB座四层4161号
法定代表人：陈春宇

乙方：
身份证号码：XX身份证号XX
户籍地址：XX户籍地址XX
联系地址：XX联系地址XX
联系电话：XX手机号XX

鉴于：
甲方已如实告知并经乙方确认其工作内容、工作条件、工作地点、职业危害、安全生产状况、劳务报酬以及乙方要求了解的其他情况，乙方自愿与甲方建立劳务关系提供相关服务；
根据《中华人民共和国民法典》等法律法规政策规定,甲乙双方遵循合法、公平、平等自愿、协商一致、诚实信用的原则订立本合同，共同遵守所列条款。

合同期限
本合同期限  XX合同月数XX  月，自  XX签订年份XX  年  XX签订月份XX  月  XX签订日期XX  日起至  XX结束年份XX  年  XX结束月份XX  月  XX结束日期XX  日止。

工作内容、工作地点
乙方工作地点为     XX工作地点XX      。

乙方的岗位为  XX岗位名称XX  ，甲方对乙方提出的基本岗位职责和要求详见附件1：基本岗位职责和要求描述。

乙方应当接受甲方对其进行的工作岗位所必需的培训。

乙方必须按照甲方确定的岗位职责，按时、按质、按量完成工作。

劳务报酬
甲方将按照如下方式向乙方发放劳务报酬：
固定报酬  XX税前工资XX  元/月（税前）。

乙方应自行缴纳各项社会保险和公积金，并自行购买医疗险、意外伤害保险等。

附件1：基本岗位职责和要求描述
XX岗位职责描述XX
"""

# 实习合同模板
INTERNSHIP_CONTRACT_TEMPLATE = """实习合同

本实习合同（下称"本合同"）由以下双方于  XX签订年份XX  年  XX签订月份XX  月  XX签订日期XX  日签订：

甲方：
注册地址：北京市海淀区中关村东路8号东升大厦AB座四层4161号
法定代表人：陈春宇

乙方：
身份证号码：XX身份证号XX
户籍地址：XX户籍地址XX
联系地址：XX联系地址XX
联系电话：XX手机号XX

鉴于：
乙方自愿与甲方建立实习关系；
根据《中华人民共和国民法典》等法律法规政策规定,甲乙双方遵循合法、公平、平等自愿、协商一致、诚实信用的原则订立本合同。

合同期限
本合同期限  XX合同月数XX  月，自  XX签订年份XX  年  XX签订月份XX  月  XX签订日期XX  日起至  XX结束年份XX  年  XX结束月份XX  月  XX结束日期XX  日止。

工作内容、工作地点
乙方工作地点为     XX工作地点XX      。

乙方的岗位为  XX岗位名称XX  ，甲方对乙方提出的基本岗位职责和要求详见附件1：基本岗位职责和要求描述。

实习报酬
甲方将按照如下方式向乙方发放实习报酬：
XX报酬方式XX

乙方应自行缴纳各项社会保险和公积金。

附件1：基本岗位职责和要求描述
XX岗位职责描述XX
"""


def generate_contract(contract_type: str, data: dict) -> str:
    """
    根据合同类型和数据生成合同
    
    contract_type: "劳动" | "劳务" | "实习"
    data: {
        "员工姓名": "张三",
        "身份证号": "1234567890",
        "户籍地址": "北京市...",
        "联系地址": "北京市...",
        "手机号": "13800138000",
        "岗位名称": "产品经理",
        "税前工资": "15000",
        "合同年限": "3",
        "试用期月数": "3",
        "工作地点": "北京市",
        "签订日期": "2026-01-20",
        "岗位职责描述": "负责产品设计..."
    }
    """
    from datetime import datetime, timedelta
    
    # 解析签订日期
    sign_date = data.get("签订日期", datetime.now().strftime("%Y-%m-%d"))
    sign_year, sign_month, sign_day = sign_date.split("-")
    
    # 计算结束日期
    contract_years = int(data.get("合同年限", "3"))
    contract_months = int(data.get("合同月数", "3"))
    
    if contract_type == "劳动":
        end_date = datetime(int(sign_year), int(sign_month), int(sign_day)) + timedelta(days=365*contract_years)
    else:
        end_date = datetime(int(sign_year), int(sign_month), int(sign_day)) + timedelta(days=30*contract_months)
    
    end_year = str(end_date.year)
    end_month = str(end_date.month).zfill(2)
    end_day = str(end_date.day).zfill(2)
    
    # 选择模板
    if contract_type == "劳动":
        template = LABOR_CONTRACT_TEMPLATE
    elif contract_type == "劳务":
        template = SERVICE_CONTRACT_TEMPLATE
    else:  # 实习
        template = INTERNSHIP_CONTRACT_TEMPLATE
    
    # 替换所有占位符
    contract = template
    replacements = {
        "XX员工姓名XX": data.get("员工姓名", ""),
        "XX身份证号XX": data.get("身份证号", ""),
        "XX户籍地址XX": data.get("户籍地址", ""),
        "XX联系地址XX": data.get("联系地址", ""),
        "XX手机号XX": data.get("手机号", ""),
        "XX岗位名称XX": data.get("岗位名称", ""),
        "XX税前工资XX": data.get("税前工资", ""),
        "XX合同年限XX": data.get("合同年限", "3"),
        "XX合同月数XX": data.get("合同月数", "3"),
        "XX试用期月数XX": data.get("试用期月数", "3"),
        "XX工作地点XX": data.get("工作地点", "北京市"),
        "XX签订年份XX": sign_year,
        "XX签订月份XX": sign_month,
        "XX签订日期XX": sign_day,
        "XX结束年份XX": end_year,
        "XX结束月份XX": end_month,
        "XX结束日期XX": end_day,
        "XX岗位职责描述XX": data.get("岗位职责描述", "详见岗位说明书"),
        "XX报酬方式XX": data.get("报酬方式", "200元/天")
    }
    
    for placeholder, value in replacements.items():
        contract = contract.replace(placeholder, value)
    
    return contract


# 保存模板到文件
if __name__ == "__main__":
    import sys
    
    # 测试数据
    test_data = {
        "员工姓名": "张三",
        "身份证号": "110101199001011234",
        "户籍地址": "北京市海淀区xxx",
        "联系地址": "北京市朝阳区xxx",
        "手机号": "13800138000",
        "岗位名称": "产品经理",
        "税前工资": "20000",
        "合同年限": "3",
        "试用期月数": "3",
        "工作地点": "北京市",
        "签订日期": "2026-03-25",
        "岗位职责描述": "1. 负责产品规划和设计\n2. 协调研发团队\n3. 跟进项目进度"
    }
    
    print("=== 劳动合同示例 ===")
    print(generate_contract("劳动", test_data))
