#!/bin/bash
# Lark Bot 健康监控脚本

BOT_URL="http://localhost:7777/health"
LOG_FILE="/var/log/lark-bot-monitor.log"
MAX_RESPONSE_TIME=10

# 记录日志
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a $LOG_FILE
}

# 检查服务健康
check_health() {
    response=$(curl -s -w "\n%{http_code}\n%{time_total}" --max-time $MAX_RESPONSE_TIME $BOT_URL 2>/dev/null)
    
    if [ $? -ne 0 ]; then
        log "ERROR: Cannot connect to bot"
        return 1
    fi
    
    http_code=$(echo "$response" | tail -2 | head -1)
    response_time=$(echo "$response" | tail -1)
    body=$(echo "$response" | head -1)
    
    if [ "$http_code" != "200" ]; then
        log "ERROR: HTTP $http_code"
        return 1
    fi
    
    # 检查响应时间
    if (( $(echo "$response_time > 5" | bc -l) )); then
        log "WARN: Slow response: ${response_time}s"
    fi
    
    log "OK: Bot healthy (${response_time}s)"
    return 0
}

# 重启服务
restart_service() {
    log "RESTARTING lark-bot service..."
    sudo systemctl restart lark-bot
    sleep 5
    
    if check_health; then
        log "RESTART SUCCESS"
    else
        log "RESTART FAILED"
    fi
}

# 主逻辑
if ! check_health; then
    restart_service
fi
