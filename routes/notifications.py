from flask import Blueprint, render_template, request, jsonify, session, current_app
from auth.utils import role_required
from services.traccar_service import full_traccar_host, get_traccar_session, save_traccar_cookies

notifications_bp = Blueprint('notifications', __name__)

@notifications_bp.route('/notifications')
@role_required('user')
def notifications_home():
    return render_template('notifications.html')

@notifications_bp.route("/api/notifications", methods=["POST"])
@role_required('admin')
def create_notification():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(force=True)
    speed = data.get("speed")
    device_ids = data.get("deviceIds")
    if not speed or not device_ids:
        return jsonify({"error": "speed and deviceIds are required"}), 400
    traccar = full_traccar_host()
    s = get_traccar_session()
    payload = {
        "type": "deviceOverspeed",
        "attributes": {"speedLimit": int(speed)},
        "always": True,
        "notificators": "command",
        "devices": device_ids
    }
    r = s.post(f"{traccar}/api/notifications", json=payload, timeout=30)
    if r.status_code not in (200, 201):
        return jsonify({"error": "failed_to_create_notification", "status": r.status_code}), 500
    return jsonify(r.json()), 201

@notifications_bp.route("/api/notifications", methods=["GET"])
def list_notifications():
    if not session.get("logged_in"):
        return jsonify([]), 401
    traccar = full_traccar_host()
    s = get_traccar_session()
    r = s.get(f"{traccar}/api/notifications", timeout=10)
    save_traccar_cookies(s)
    if r.status_code != 200:
        return jsonify([]), 500
    return jsonify(r.json())

@notifications_bp.route("/api/notification-rules", methods=["GET"])
def list_notification_rules():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    traccar = full_traccar_host()
    s = get_traccar_session()
    r = s.get(f"{traccar}/api/notifications", timeout=10)
    if r.status_code != 200:
        return jsonify({"error": "failed_to_fetch_rules"}), 500
    return jsonify(r.json())

@notifications_bp.route("/api/notification-rules", methods=["POST"])
@role_required('admin')
def create_notification_rule():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(force=True)
    rule_type = data.get("type")
    channels = data.get("channels", [])
    if not rule_type:
        return jsonify({"error": "type is required"}), 400
    if not channels:
        return jsonify({"error": "at least one channel is required"}), 400
    traccar = full_traccar_host()
    s = get_traccar_session()
    payload = {
        "type": rule_type,
        "notificators": ",".join(channels),
        "always": data.get("always", False),
        "attributes": data.get("attributes", {})
    }
    if data.get("description"): payload["description"] = data["description"]
    if data.get("calendarId"): payload["calendarId"] = data["calendarId"]
    elif data.get("calendar"): payload["calendarId"] = data["calendar"]
    if data.get("priority"):
        if "attributes" not in payload: payload["attributes"] = {}
        payload["attributes"]["priority"] = data.get("priority")
    device_ids = data.get("deviceIds", [])
    try:
        r = s.post(f"{traccar}/api/notifications", json=payload, timeout=10)
        save_traccar_cookies(s)
        if r.status_code not in (200, 201):
            return jsonify({"error": "failed_to_create_rule", "status": r.status_code}), 500
        created_rule = r.json()
        notification_id = created_rule.get("id")
        if not payload["always"] and device_ids and notification_id:
            for device_id in device_ids:
                link_payload = {"notificationId": notification_id, "deviceId": int(device_id)}
                s.post(f"{traccar}/api/permissions", json=link_payload, timeout=10)
        return jsonify(created_rule), 201
    except Exception as e:
        current_app.logger.exception("Error creating notification rule")
        return jsonify({"error": str(e)}), 500

@notifications_bp.route("/api/notification-rules/<int:rule_id>", methods=["DELETE"])
@role_required('admin')
def delete_notification_rule(rule_id):
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    traccar = full_traccar_host()
    s = get_traccar_session()
    try:
        r = s.delete(f"{traccar}/api/notifications/{rule_id}", timeout=10)
        save_traccar_cookies(s)
        if r.status_code == 204: return jsonify({"success": True}), 200
        elif r.status_code == 404: return jsonify({"error": "rule_not_found"}), 404
        else: return jsonify({"error": "failed_to_delete_rule", "status": r.status_code}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
