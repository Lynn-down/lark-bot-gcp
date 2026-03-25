#!/usr/bin/env python3
"""
修复 Bitable 写入权限 - 正确参数版：type=bitable（非 token_type）
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

APP_ID     = os.environ["LARK_APP_ID"]
APP_SECRET = os.environ["LARK_APP_SECRET"]
BASE       = "https://open.larksuite.com/open-apis"
APP_TOKEN  = "OlXRbRKn1a5hyOsJ10Ml7oF4g3Y"
TABLE_ID   = "tblBJz4F3owR3gOB"

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
        return "OK write works"
    return f"FAIL {d}"

tok = get_tok()

print("=== 1. 查询当前公开权限（type=bitable）===")
r = requests.get(
    f"{BASE}/drive/v1/permissions/{APP_TOKEN}/public",
    params={"type": "bitable"},                        # ← 关键修正
    headers={"Authorization": f"Bearer {tok}"}, timeout=10)
print(r.json())

print("\n=== 2. 设置组织内可编辑（tenant_editable）===")
r = requests.patch(
    f"{BASE}/drive/v1/permissions/{APP_TOKEN}/public",
    params={"type": "bitable"},                        # ← 关键修正
    headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    json={"link_share_entity": "tenant_editable"}, timeout=10)
d = r.json()
print(d)
if d.get("code") == 0:
    print("*** 权限设置成功 ***")

print("\n=== 3. 写入测试 ===")
print(write_test(tok))
