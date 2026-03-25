#!/usr/bin/env python3
"""
诊断并修复 Bitable 写入权限（91403）
运行方式：.venv/bin/python fix_bitable_perm.py
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

APP_ID     = os.environ["LARK_APP_ID"]
APP_SECRET = os.environ["LARK_APP_SECRET"]
BASE       = "https://open.larksuite.com/open-apis"
BITABLE_TOKEN = "Lpbhb302ZaVHmmsmbeCuhqQMsBd"  # 从 URL 取到的 app_token

def get_tenant_token():
    r = requests.post(f"{BASE}/auth/v3/tenant_access_token/internal",
                      json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=10)
    d = r.json()
    assert d["code"] == 0, f"token failed: {d}"
    return d["tenant_access_token"]

def check_app_info(tok):
    """检查 bitable 基本信息（测试读权限）"""
    r = requests.get(f"{BASE}/bitable/v1/apps/{BITABLE_TOKEN}",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    print("[GET app info]", r.json())

def try_grant_via_drive(tok):
    """通过 Drive 权限 API 给 bot 加编辑权限"""
    r = requests.post(
        f"{BASE}/drive/v1/permissions/{BITABLE_TOKEN}/members",
        params={"token_type": "bitable", "need_notification": "false"},
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        json={"member_type": "app", "member_id": APP_ID, "perm": "edit"},
        timeout=10
    )
    print("[Drive grant edit]", r.json())

def try_write_test(tok):
    """尝试写一条测试记录（用来判断是否真的有写权限）"""
    # 先拿 table_id
    from bitable_client import HR_BOARD_TABLE_ID
    r = requests.post(
        f"{BASE}/bitable/v1/apps/{BITABLE_TOKEN}/tables/{HR_BOARD_TABLE_ID}/records",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        json={"fields": {"__test__": "ping"}},
        timeout=10
    )
    d = r.json()
    print("[Write test]", d)
    # 如果成功，立刻删掉测试记录
    if d.get("code") == 0:
        rid = d["data"]["record"]["record_id"]
        requests.delete(
            f"{BASE}/bitable/v1/apps/{BITABLE_TOKEN}/tables/{HR_BOARD_TABLE_ID}/records/{rid}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10
        )
        print("  (测试记录已删除)")

tok = get_tenant_token()
print(f"\nApp ID: {APP_ID}\n")

print("=== 1. 读取 bitable 信息 ===")
check_app_info(tok)

print("\n=== 2. 尝试通过 Drive API 授予编辑权限 ===")
try_grant_via_drive(tok)

print("\n=== 3. 再次尝试写入测试 ===")
try_write_test(tok)
