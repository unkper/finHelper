# app/services/feishu.py
import json
import hashlib
import base64

import requests
from Crypto.Cipher import AES
from flask import current_app

from app.services.rate_limit import consume_rate_limit


class AESCipher:
    def __init__(self, key):
        self.key = hashlib.sha256(key.encode('utf-8')).digest()

    def decrypt(self, encrypt_text):
        encrypt_text = base64.b64decode(encrypt_text)
        iv = encrypt_text[:AES.block_size]
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        decrypted_text = cipher.decrypt(encrypt_text[AES.block_size:])
        padding_len = decrypted_text[-1]
        decrypted_text = decrypted_text[:-padding_len]
        return decrypted_text.decode('utf-8')


def get_cipher():
    """获取实例化后的解密器"""
    encrypt_key = current_app.config.get("FEISHU_ENCRYPT_KEY")
    return AESCipher(encrypt_key) if encrypt_key else None


def get_tenant_access_token():
    """获取飞书 Tenant Access Token"""
    app_id = current_app.config.get("FEISHU_APP_ID")
    app_secret = current_app.config.get("FEISHU_APP_SECRET")
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    res = requests.post(url, json={"app_id": app_id, "app_secret": app_secret})
    return res.json().get("tenant_access_token")


def reply_feishu_message(message_id, content):
    """被动：回复用户的消息"""
    allowed, _ = consume_rate_limit("feishu:reply:global", max_calls=60, window_seconds=60)
    if not allowed:
        print("飞书被动回复被限流，已跳过")
        return False

    token = get_tenant_access_token()
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    payload = {
        "msg_type": "text",
        "content": json.dumps({"text": content})
    }
    resp = requests.post(url, headers=headers, json=payload)
    return resp.ok


def push_feishu_message(receive_id_type, receive_id, content):
    """主动：给特定用户或群组推送消息 (用于时间线告警)"""
    allowed, _ = consume_rate_limit("feishu:push:global", max_calls=40, window_seconds=60)
    if not allowed:
        print("飞书主动推送被限流，已跳过本次发送以保护 API 配额")
        return False

    token = get_tenant_access_token()
    url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    payload = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": content})
    }
    resp = requests.post(url, headers=headers, json=payload)
    print(resp.json())
    return resp.ok
