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
WIKI_TOKEN = "LUI3wLWbliXDy9kWx4MlW0KvgXs"
TABLE_ID   = "tblBJz4F3owR3gOB"

def get_tenant_token():
    r = requests.post(f"{BASE}/auth/v3/tenant_access_token/internal",
                      json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=10)
    d = r.json()
    assert d["code"] == 0, f"token failed: {d}"
    return d["tenant_access_token"]

def get_bot_info(tok):
    r = requests.get(f"{BASE}/bot/v3/info",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    return r.json()

def resolve_app_token(tok):
    r = requests.get(f"{BASE}/wiki/v2/spaces/get_node",
                     params={"token": WIKI_TOKEN},
                     headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    d = r.json()
    if d.get("code") == 0:
        return d["data"]["node"].get("obj_token")
    print(f"  wiki resolve failed: {d}")
    return None

def list_roles(tok, app_token):
    r = requests.get(f"{BASE}/bitable/v1/apps/{app_token}/roles",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    return r.json()

def add_to_role(tok, app_token, role_id, open_id):
    r = requests.post(
        f"{BASE}/bitable/v1/apps/{app_token}/roles/{role_id}/members",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        json={"member_list": [{"type": "open_id", "id": open_id}]},
        timeout=10
    )
    return r.json()

def try_drive_openid(tok, app_token, open_id):
    r = requests.post(
        f"{BASE}/drive/v1/permissions/{app_token}/members",
        params={"token_type": "bitable", "need_notification": "false"},
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        json={"member_type": "openid", "member_id": open_id, "perm": "edit"},
        timeout=10
    )
    return r.json()

def write_test(tok, app_token):
    r = requests.post(
        f"{BASE}/bitable/v1/apps/{app_token}/tables/{TABLE_ID}/records",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        json={"fields": {"__ping__": "test"}}, timeout=10
    )
    d = r.json()
    if d.get("code") == 0:
        rid = d["data"]["record"]["record_id"]
        requests.delete(
            f"{BASE}/bitable/v1/apps/{app_token}/tables/{TABLE_ID}/records/{rid}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10
        )
        return "OK write success (test record deleted)"
    return f"FAIL {d}"

# ── 执行 ─────────────────────────────────────────────────────────────────────
tok = get_tenant_token()
print(f"App ID: {APP_ID}\n")

print("=== 1. Bot 信息 ===")
bot_info = get_bot_info(tok)
print(bot_info)
open_id = bot_info.get("bot", {}).get("open_id", "")
print(f"Bot open_id: {open_id}\n")

print("=== 2. 解析真实 app_token ===")
app_token = resolve_app_token(tok)
print(f"app_token: {app_token}\n")
if not app_token:
    exit(1)

print("=== 3. 列出 bitable 角色 ===")
roles_resp = list_roles(tok, app_token)
print(roles_resp)

if roles_resp.get("code") == 0 and open_id:
    items = roles_resp.get("data", {}).get("items", [])
    print(f"共 {len(items)} 个角色")
    for role in items:
        print(f"  {role['role_id']} | {role.get('role_name','')}")
        res = add_to_role(tok, app_token, role["role_id"], open_id)
        print(f"  add_to_role result: {res}")
elif open_id:
    print("角色列表失败，尝试 Drive openid 方式")
    dr = try_drive_openid(tok, app_token, open_id)
    print(f"Drive openid: {dr}")

print("\n=== 4. 写入测试 ===")
print(write_test(tok, app_token))
