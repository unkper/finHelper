from flask import Blueprint, jsonify, current_app
from app.services.feishu import push_feishu_message
from app.services.rate_limit import consume_rate_limit, get_client_ip, rate_limit_response_message

bp = Blueprint('debug', __name__, url_prefix='/debug')


@bp.route('/test-push', methods=['GET'])
def test_push():
    ip = get_client_ip()
    allowed, retry_after = consume_rate_limit(f"feishu:test-push:{ip}", max_calls=3, window_seconds=3600)
    if not allowed:
        return jsonify({
            "status": "error",
            "message": rate_limit_response_message(retry_after),
        }), 429

    receiver_id = current_app.config.get("FEISHU_ALERT_RECEIVER_ID")
    receiver_type = current_app.config.get("FEISHU_ALERT_RECEIVER_TYPE", "open_id")
    print("id:{}, type:{}".format(receiver_id, receiver_type))

    if not receiver_id:
        return jsonify({"status": "error", "message": "配置中没有 FEISHU_ALERT_RECEIVER_ID"})

    try:
        if not push_feishu_message(receiver_type, receiver_id, "这是来自 FinHelper 的测试消息！🚀"):
            return jsonify({"status": "error", "message": "飞书推送被限流，请稍后再试"})
        return jsonify({"status": "success", "message": "消息已推送"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})