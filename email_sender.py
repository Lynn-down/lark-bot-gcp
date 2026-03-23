#!/usr/bin/env python3
"""
邮件发送配置 - 使用腾讯企业邮
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os

# SMTP配置 - 腾讯企业邮
SMTP_SERVER = "smtp.exmail.qq.com"
SMTP_PORT = 465  # SSL端口
SMTP_USER = "jyx@group-ultra.com"
SMTP_PASSWORD = "lynn5121122"


def send_contract_email(
    to_email: str,
    contract_path: str,
    employee_name: str,
    contract_type: str
) -> dict:
    """
    发送合同邮件
    
    Returns:
        dict: {'success': bool, 'message': str}
    """
    try:
        # 创建邮件
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = to_email
        msg['Subject'] = f"【北京极群科技】{employee_name}的{contract_type}"
        
        # 邮件正文
        body = f"""您好，

{employee_name}的{contract_type}已生成，请查收附件。

合同信息：
- 员工姓名：{employee_name}
- 合同类型：{contract_type}
- 生成时间：自动生成

如有疑问，请联系HR部门。

此邮件由HR系统自动发送
北京极群科技有限公司
"""
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # 添加附件
        if os.path.exists(contract_path):
            with open(contract_path, 'rb') as f:
                attachment = MIMEBase('application', 'vnd.openxmlformats-officedocument.wordprocessingml.document')
                attachment.set_payload(f.read())
            
            encoders.encode_base64(attachment)
            filename = os.path.basename(contract_path)
            attachment.add_header(
                'Content-Disposition',
                f'attachment; filename="{filename}"'
            )
            msg.attach(attachment)
        else:
            return {'success': False, 'message': '合同文件不存在'}
        
        # 发送邮件 - 使用SSL
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        return {'success': True, 'message': f'合同已发送至 {to_email}'}
        
    except Exception as e:
        return {'success': False, 'message': f'邮件发送失败: {str(e)}'}


if __name__ == "__main__":
    # 测试
    result = send_contract_email(
        to_email="jyx@group-ultra.com",
        contract_path="/tmp/test_contract.docx",
        employee_name="测试",
        contract_type="劳动合同"
    )
    print(result)
