#!/usr/bin/env python3
"""
修复 Bitable 写入权限 - 通过 Drive API 给 bot 加 editor
运行方式：.venv/bin/python fix_bitable_perm.py
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

APP_ID     = os.environ["LARK_APP_ID"]
APP_SECRET = os.environ["LARK_APP_SECRET"]
BASE       = "https://open.larksuite.com/open-apis"
APP_TOKEN  = "OlXRbRKn1a5hyOsJ10Ml7oF4g3Y"   # 真实 bitable app_token
TABLE_ID   = "tblBJz4F3owR3gOB"
BOT_OPEN_ID = "ou_bf1b5942e692731fd47e364343e44587"

def get_tok():
    r = requests.post(f"{BASE}/auth/v3/tenant_access_token/internal",
                      json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=10)
    d = r.json(); assert d["code"] == 0; return d["tenant_access_token"]

def write_test(tok):
    r = requests.post(
        f"{BASE}/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        json={"fields": {"__ping__": "test"}}, timeout=10)
    d = r.json()
    if d.get("code") == 0:
        rid = d["data"]["record"]["record_id"]
        requests.delete(f"{BASE}/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/{rid}",
                        headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        return "OK (test record deleted)"
    return f"FAIL {d}"

tok = get_tok()

# 尝试各种 Drive API 参数组合
combos = [
    {"type": "user",       "member_type": "openid",  "member_id": BOT_OPEN_ID, "perm": "edit"},
    {"type": "openid",     "member_id": BOT_OPEN_ID, "perm": "edit"},
    {"type": "user",       "member_id": BOT_OPEN_ID, "perm": "edit"},
]

print("=== Drive API 参数组合尝试 ===")
for i, body in enumerate(combos, 1):
    r = requests.post(
        f"{BASE}/drive/v1/permissions/{APP_TOKEN}/members",
        params={"token_type": "bitable", "need_notification": "false"},
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        json=body, timeout=10)
    d = r.json()
    print(f"[{i}] body={body}")
    print(f"    result={d}")
    if d.get("code") == 0:
        print("    *** SUCCESS ***")
        break

print("\n=== 写入测试 ===")
print(write_test(tok))
