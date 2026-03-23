#!/usr/bin/env python3
"""
邮件发送配置 - 使用163邮箱
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os

# SMTP配置 - 163邮箱
SMTP_SERVER = "smtp.163.com"
SMTP_PORT = 465
SMTP_USER = "18924538056@163.com"
SMTP_PASSWORD = "MKpTGYXJZ2T9PjLB"  # 授权码

DEFAULT_HR_EMAIL = "18924538056@163.com"


def send_contract_email(to_email, contract_path, employee_name, contract_type):
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = to_email
        msg['Subject'] = f"【北京极群科技】{employee_name}的{contract_type}"
        
        body = f"""您好，

{employee_name}的{contract_type}已生成，请查收附件。

合同信息：
- 员工姓名：{employee_name}
- 合同类型：{contract_type}
- 生成时间：自动生成

此邮件由HR系统自动发送
北京极群科技有限公司
"""
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        if os.path.exists(contract_path):
            with open(contract_path, 'rb') as f:
                attachment = MIMEBase('application', 'vnd.openxmlformats-officedocument.wordprocessingml.document')
                attachment.set_payload(f.read())
            encoders.encode_base64(attachment)
            filename = os.path.basename(contract_path)
            attachment.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(attachment)
        else:
            return {'success': False, 'message': '合同文件不存在'}
        
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        return {'success': True, 'message': f'合同已发送至 {to_email}'}
    except Exception as e:
        return {'success': False, 'message': f'邮件发送失败: {str(e)}'}


def send_contract_with_fallback(to_email, contract_path, employee_name, contract_type):
    return send_contract_email(to_email, contract_path, employee_name, contract_type)
