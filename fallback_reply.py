# 临时回退回复，当LLM不可用时使用

def get_fallback_reply(user_message, is_hr=False):
    msg = user_message.lower()
    
    # 名册查询
    if any(kw in msg for kw in ['是谁', '的资料', '的信息']):
        return None  # 让系统使用名册查询
    
    # 统计查询
    if any(kw in msg for kw in ['多少', '几个', '人数', '统计']):
        return None  # 让系统使用统计查询
    
    # 入职查询
    if any(kw in msg for kw in ['入职', '新员工', '报到']):
        return None  # 让系统使用入职查询
    
    # 公司信息
    if any(kw in msg for kw in ['公司', '地址', 'wifi', '密码']):
        return None  # 让系统使用公司信息查询
    
    # 默认回复
    replies = [
         我现在有点忙，请稍后再试～,
        收到你的消息啦，但我现在脑子有点卡🤯,
        这个问题我暂时回答不了，你可以问问陆俊豪～,
        哎呀，我需要休息一下，等会再聊！
    ]
    import random
    return random.choice(replies)
