#!/usr/bin/env python3
"""
设置两个 bitable 的组织内权限：
  OlXRbRKn1a5hyOsJ10Ml7oF4g3Y  → HR看板（目标 tenant_editable）
  Lpbhb302ZaVHmmsmbeCuhqQMsBd  → 成员名册（目标 tenant_readable）
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

APP_ID     = os.environ["LARK_APP_ID"]
APP_SECRET = os.environ["LARK_APP_SECRET"]
BASE       = "https://open.larksuite.com/open-apis"

TARGETS = [
    ("OlXRbRKn1a5hyOsJ10Ml7oF4g3Y", "tenant_editable", "HR看板"),
    ("Lpbhb302ZaVHmmsmbeCuhqQMsBd",  "tenant_readable",  "成员名册"),
]

def get_tok():
    r = requests.post(f"{BASE}/auth/v3/tenant_access_token/internal",
                      json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=10)
    d = r.json(); assert d["code"] == 0; return d["tenant_access_token"]

tok = get_tok()

for app_token, target_perm, label in TARGETS:
    print(f"\n=== {label} ({app_token}) ===")
    # 查当前
    r = requests.get(f"{BASE}/drive/v1/permissions/{app_token}/public",
                     params={"type": "bitable"},
                     headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    d = r.json()
    current = d.get("data", {}).get("permission_public", {}).get("link_share_entity", "unknown")
    print(f"当前权限: {current}")

    if current == target_perm:
        print("已是目标权限，跳过")
        continue

    # 修改
    r = requests.patch(f"{BASE}/drive/v1/permissions/{app_token}/public",
                       params={"type": "bitable"},
                       headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                       json={"link_share_entity": target_perm}, timeout=10)
    d = r.json()
    if d.get("code") == 0:
        print(f"✅ 已设置为 {target_perm}")
    else:
        print(f"❌ 设置失败（需手动在UI改）: {d.get('code')} {d.get('msg')}")
        if label == "成员名册":
            print("   → 打开 https://groupultra.sg.larksuite.com/base/Lpbhb302ZaVHmmsmbeCuhqQMsBd")
            print("   → 分享 → 组织内链接 → 改为「可查看」")
