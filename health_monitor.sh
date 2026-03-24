#!/bin/bash
# Lark Bot 健康监控脚本

BOT_URL= http://localhost:7777/health
LOG_FILE=/var/log/lark-bot-monitor.log
MAX_RESPONSE_TIME=10

# 记录日志
log() {
    echo [\] \ | tee -a \
}

# 检查服务健康
check_health() {
    response=\
    
    if [ \False -ne 0 ]; then
        log ERROR: Cannot connect to bot
        return 1
    fi
    
    http_code=\
    
    if [ \ != 200 ]; then
        log ERROR: HTTP \
        return 1
    fi
    
    log OK: Bot healthy
    return 0
}

# 重启服务
restart_service() {
    log RESTARTING lark-bot service...
    sudo systemctl restart lark-bot
    sleep 5
    
    if check_health; then
        log RESTART SUCCESS
    else
        log RESTART FAILED
    fi
}

# 主逻辑
if ! check_health; then
    restart_service
fi
