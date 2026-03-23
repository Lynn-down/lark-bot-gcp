#!/usr/bin/env python3
"""
邮件发送模块 - 发送合同到指定邮箱
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os

def send_contract_email(
    to_email: str,
    contract_path: str,
    employee_name: str,
    contract_type: str,
    smtp_server: str = "smtp.gmail.com",
    smtp_port: int = 587,
    smtp_user: str = None,
    smtp_password: str = None
) -> bool:
    """
    发送合同邮件
    
    Args:
        to_email: 收件人邮箱
        contract_path: 合同文件路径
        employee_name: 员工姓名
        contract_type: 合同类型
        smtp_server: SMTP服务器
        smtp_port: SMTP端口
        smtp_user: SMTP用户名
        smtp_password: SMTP密码
    
    Returns:
        bool: 是否发送成功
    """
    try:
        # 从环境变量获取邮件配置
        if not smtp_user:
            smtp_user = os.environ.get('SMTP_USER', 'hr@group-ultra.com')
        if not smtp_password:
            smtp_password = os.environ.get('SMTP_PASSWORD', '')
        
        # 创建邮件
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = to_email
        msg['Subject'] = f"【北京极群科技】{employee_name}的{contract_type}合同"
        
        # 邮件正文
        body = f"""您好，

{employee_name}的{contract_type}合同已生成，请查收附件。

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
                attachment = MIMEBase('application', 'octet-stream')
                attachment.set_payload(f.read())
            
            encoders.encode_base64(attachment)
            filename = os.path.basename(contract_path)
            attachment.add_header(
                'Content-Disposition',
                f'attachment; filename= "{filename}"'
            )
            msg.attach(attachment)
        
        # 发送邮件
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        print(f"发送邮件失败: {e}")
        return False


def send_contract_with_fallback(
    to_email: str,
    contract_path: str,
    employee_name: str,
    contract_type: str
) -> dict:
    """
    发送合同邮件，带错误处理
    
    Returns:
        dict: {'success': bool, 'message': str}
    """
    # 尝试多个SMTP服务器
    smtp_configs = [
        # Gmail
        {"server": "smtp.gmail.com", "port": 587},
        # QQ邮箱
        {"server": "smtp.qq.com", "port": 587},
        # 163邮箱
        {"server": "smtp.163.com", "port": 25},
        # Outlook
        {"server": "smtp.office365.com", "port": 587},
    ]
    
    for config in smtp_configs:
        try:
            success = send_contract_email(
                to_email=to_email,
                contract_path=contract_path,
                employee_name=employee_name,
                contract_type=contract_type,
                smtp_server=config["server"],
                smtp_port=config["port"]
            )
            if success:
                return {
                    'success': True,
                    'message': f'合同已发送至 {to_email}'
                }
        except Exception as e:
            continue
    
    # 所有SMTP都失败
    return {
        'success': False,
        'message': '邮件发送失败，请检查SMTP配置或手动下载文件'
    }


if __name__ == "__main__":
    # 测试
    result = send_contract_with_fallback(
        to_email="jyx@group-ultra.com",
        contract_path="/tmp/test_contract.docx",
        employee_name="张三",
        contract_type="劳动合同"
    )
    print(result)
