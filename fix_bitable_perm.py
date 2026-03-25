#!/usr/bin/env python3
"""
修复 Bitable 写入权限
策略：把组织内链接权限改为「可编辑」，这样 bot 的 tenant_access_token 就有写权限
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

APP_ID      = os.environ["LARK_APP_ID"]
APP_SECRET  = os.environ["LARK_APP_SECRET"]
BASE        = "https://open.larksuite.com/open-apis"
APP_TOKEN   = "OlXRbRKn1a5hyOsJ10Ml7oF4g3Y"
TABLE_ID    = "tblBJz4F3owR3gOB"

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

print("=== 1. 查询当前公开权限设置 ===")
r = requests.get(
    f"{BASE}/drive/v1/permissions/{APP_TOKEN}/public",
    params={"token_type": "bitable"},
    headers={"Authorization": f"Bearer {tok}"}, timeout=10)
print(r.json())

print("\n=== 2. 尝试将组织内链接改为「可编辑」===")
# link_share_entity 可能的值：
# tenant_editable / anyone_editable / tenant_readable / closed
for val in ["tenant_editable", "tenant_can_edit", "edit"]:
    r = requests.patch(
        f"{BASE}/drive/v1/permissions/{APP_TOKEN}/public",
        params={"token_type": "bitable"},
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        json={"link_share_entity": val}, timeout=10)
    d = r.json()
    print(f"  link_share_entity={val!r}: {d}")
    if d.get("code") == 0:
        print("  *** 成功 ***")
        break

print("\n=== 3. 写入测试 ===")
print(write_test(tok))
