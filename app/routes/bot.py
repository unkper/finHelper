# app/routes/bot.py
import json
import threading
from flask import Blueprint, request, jsonify, current_app
from app.services.feishu import get_cipher, reply_feishu_message

bp = Blueprint('bot', __name__, url_prefix='/bot')


def handle_feishu_event_async(data):
    """异步处理飞书消息的具体逻辑 (脱离当前 HTTP 请求阻塞)"""
    # 因为在线程中，如果需要使用 Flask 上下文获取配置或数据库，必须手动推入 app_context
    app = current_app._get_current_object()

    with app.app_context():
        event = data.get("event", {})
        msg = event.get("message", {})
        if not msg:
            return

        message_id = msg.get("message_id")
        try:
            content_json = json.loads(msg.get("content"))
            raw_text = content_json.get("text", "").strip()
            # 简单的回复测试
            print(f"收到飞书消息: {raw_text}")
            if "测试" in raw_text:
                reply_feishu_message(message_id, "FinHelper 机器人已就绪！")
        except Exception as e:
            print(f"处理飞书消息失败: {e}")


@bp.route('/callback', methods=['POST'])
def feishu_callback():
    raw_data = request.json
    data = raw_data

    # 判断是否加密，如果加密则先解密
    if "encrypt" in raw_data:
        try:
            cipher = get_cipher()
            decrypted_str = cipher.decrypt(raw_data["encrypt"])
            data = json.loads(decrypted_str)
        except Exception as e:
            print(f"解密失败: {e}")
            return jsonify({"message": "decrypt failed"}), 400

    # 处理飞书的 URL 验证挑战 (Url Verification)
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    # 异步处理正常消息 (把 data 丢给子线程去处理)
    threading.Thread(target=handle_feishu_event_async, args=(data,)).start()

    return jsonify({"msg": "success"}), 200