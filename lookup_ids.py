#!/usr/bin/env python3
"""查询用户ID + HR看板实际字段名"""
import os, requests
from dotenv import load_dotenv
load_dotenv()
APP_ID = os.environ['LARK_APP_ID']
APP_SECRET = os.environ['LARK_APP_SECRET']
FEISHU = 'https://open.feishu.cn/open-apis'
LARK   = 'https://open.larksuite.com/open-apis'

r = requests.post(f'{FEISHU}/auth/v3/tenant_access_token/internal',
                  json={'app_id': APP_ID, 'app_secret': APP_SECRET})
tok = r.json()['tenant_access_token']

print('=== 用户ID（手机号查询）===')
r = requests.post(f'{FEISHU}/contact/v3/users/batch_get_id',
    headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
    json={'mobiles': ['13260466971', '15300296932']})
print(r.json())

print('\n=== HR看板实际字段名 ===')
r = requests.get(f'{LARK}/bitable/v1/apps/OlXRbRKn1a5hyOsJ10Ml7oF4g3Y/tables/tblBJz4F3owR3gOB/fields',
    headers={'Authorization': f'Bearer {tok}'})
d = r.json()
if d.get('code') == 0:
    for f in d['data']['items']:
        print(f"  {f['field_name']!r}  type={f['type']}")
else:
    print(d)
