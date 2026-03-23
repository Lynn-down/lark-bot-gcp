import requests
url = 'https://api.ablai.top/v1/chat/completions'
headers = {
    'Authorization': 'Bearer sk-7FcrRYLb9Jv4mNa2SbztlCky8uGHYs1T968CHILzwRiGQ8Lg',
    'Content-Type': 'application/json'
}
data = {
    'model': 'gpt-4o-mini',
    'messages': [{'role': 'user', 'content': 'hi'}]
}
try:
    r = requests.post(url, headers=headers, json=data, timeout=30)
    print('Status:', r.status_code)
    print('Response:', r.text[:300])
except Exception as e:
    print('Error:', e)
