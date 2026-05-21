from flask import Blueprint, jsonify, current_app
from app.services.feishu import push_feishu_message

bp = Blueprint('debug', __name__, url_prefix='/debug')


@bp.route('/test-push', methods=['GET'])
def test_push():
    # 从配置中读取 ID 和类型
    receiver_id = current_app.config.get("FEISHU_ALERT_RECEIVER_ID")
    receiver_type = current_app.config.get("FEISHU_ALERT_RECEIVER_TYPE", "open_id")
    print("id:{}, type:{}".format(receiver_id, receiver_type))

    if not receiver_id:
        return jsonify({"status": "error", "message": "配置中没有 FEISHU_ALERT_RECEIVER_ID"})

    try:
        push_feishu_message(receiver_type, receiver_id, "这是来自 FinHelper 的测试消息！🚀")
        return jsonify({"status": "success", "message": "消息已推送"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})