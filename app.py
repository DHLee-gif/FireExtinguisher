from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from werkzeug.security import check_password_hash

import config
import labels
import state
from api import bp as rc_api
from db import SessionLocal
from models import Admin, Device, FireEvent, StatusLog, WaterLog

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024
app.register_blueprint(rc_api)

PUBLIC_ENDPOINTS = {"login", "static"}


@app.before_request
def login_required():
    endpoint = request.endpoint or ""
    if endpoint in PUBLIC_ENDPOINTS or endpoint.startswith("rc_api."):
        return
    if session.get("admin_id") is None:
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error="로그인이 필요합니다."), 401
        return redirect(url_for("login"))


@app.errorhandler(OperationalError)
def db_unavailable(e):
    app.logger.error("DB 연결 실패: %s", e.orig if hasattr(e, "orig") else e)
    if request.path.startswith("/api/"):
        return jsonify(ok=False, error="DB 연결 실패"), 503
    return render_template("db_error.html", config_db=f"{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}"), 503


@app.context_processor
def inject_labels():
    return {
        "ACTION_LABELS": labels.ACTION_LABELS,
        "LEVEL_LABELS": labels.LEVEL_LABELS,
        "FIRE_STATUS_LABELS": labels.FIRE_STATUS_LABELS,
        "WATER_ACTION_LABELS": labels.WATER_ACTION_LABELS,
    }


@app.template_filter("dt")
def format_datetime(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else "-"


@app.template_filter("num")
def format_number(value, digits=1):
    return f"{value:.{digits}f}" if value is not None else "-"


def get_device_status(db):
    row = db.execute(
        select(Device, func.timestampdiff(text("SECOND"), Device.last_seen, func.now()))
        .where(Device.device_id == config.DEVICE_ID)
    ).first()
    if row is None:
        return None, False, None
    device, elapsed = row
    online = elapsed is not None and elapsed <= config.ONLINE_TIMEOUT_SEC
    return device, online, elapsed


def get_latest_water(db):
    return db.scalars(select(WaterLog).order_by(WaterLog.log_id.desc()).limit(1)).first()


def get_unresolved_errors(db):
    return db.scalars(
        select(StatusLog)
        .where(StatusLog.level == "error", StatusLog.resolved_at.is_(None))
        .order_by(StatusLog.log_id)
    ).all()


def get_latest_event(db):
    return db.scalars(select(FireEvent).order_by(FireEvent.event_id.desc()).limit(1)).first()


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_id") is not None:
        return redirect(url_for("index"))

    error = None
    login_id = ""
    if request.method == "POST":
        login_id = request.form.get("login_id", "").strip()
        password = request.form.get("password", "")

        if config.LOGIN_BYPASS:
            session.clear()
            session["admin_id"] = 0
            session["admin_login_id"] = login_id or "dev"
            session["admin_name"] = login_id or "관리자"
            return redirect(url_for("index"))

        with SessionLocal() as db:
            admin = db.scalar(select(Admin).where(Admin.login_id == login_id))
        if admin and check_password_hash(admin.password_hash, password):
            session.clear()
            session["admin_id"] = admin.admin_id
            session["admin_login_id"] = admin.login_id
            session["admin_name"] = admin.name
            return redirect(url_for("index"))
        error = "아이디 또는 비밀번호가 올바르지 않습니다."

    return render_template("login.html", error=error, login_id=login_id, bypass=config.LOGIN_BYPASS)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    try:
        with SessionLocal() as db:
            latest = get_latest_event(db)
    except OperationalError:
        latest = None
    return render_template(
        "index.html",
        stream_url=config.STREAM_URL,
        poll_ms=config.LIVE_POLL_MS,
        last_event_id=latest.event_id if latest else 0,
    )


@app.route("/admin")
def admin_info():
    db_ok = True
    try:
        with SessionLocal() as db:
            admin = db.get(Admin, session["admin_id"])
            device, online, _ = get_device_status(db)
    except OperationalError:
        db_ok, admin, device, online = False, None, None, False
    if admin is None:
        if not config.LOGIN_BYPASS:
            session.clear()
            return redirect(url_for("login"))
        admin = {"name": session.get("admin_name"), "login_id": session.get("admin_login_id")}
    return render_template("admin.html", admin=admin, device=device, online=online, db_ok=db_ok)


@app.route("/fire")
def fire_list():
    with SessionLocal() as db:
        events = db.scalars(
            select(FireEvent).order_by(FireEvent.detected_at.desc(), FireEvent.event_id.desc())
            .limit(config.LIST_LIMIT)
        ).all()
    return render_template("fire_list.html", events=events)


@app.route("/fire/<int:event_id>")
def fire_detail(event_id):
    with SessionLocal() as db:
        event = db.get(FireEvent, event_id)
        if event is None:
            abort(404)
        before = [img for img in event.images if img.img_type == "before"]
        after = [img for img in event.images if img.img_type == "after"]
        sprays = list(event.sprays)
    return render_template("fire_detail.html", event=event, before=before, after=after, sprays=sprays)


@app.route("/status")
def status_log():
    level = request.args.get("level", "")
    unresolved = request.args.get("unresolved") == "1"

    stmt = select(StatusLog)
    if unresolved:
        stmt = stmt.where(StatusLog.level == "error", StatusLog.resolved_at.is_(None))
    elif level in labels.LEVEL_LABELS:
        stmt = stmt.where(StatusLog.level == level)

    with SessionLocal() as db:
        logs = db.scalars(stmt.order_by(StatusLog.log_id.desc()).limit(config.LIST_LIMIT)).all()
    return render_template("status.html", logs=logs, level=level, unresolved=unresolved)


@app.route("/water")
def water_log():
    with SessionLocal() as db:
        logs = db.scalars(select(WaterLog).order_by(WaterLog.log_id.desc()).limit(config.LIST_LIMIT)).all()
    current = logs[0] if logs else None
    return render_template("water.html", logs=logs, current=current)


@app.get("/api/live")
def api_live():
    db_ok = True
    try:
        with SessionLocal() as db:
            device, online, elapsed = get_device_status(db)
            errors = get_unresolved_errors(db)
            latest_log = db.scalars(select(StatusLog).order_by(StatusLog.log_id.desc()).limit(1)).first()
            latest_event = get_latest_event(db)
            latest_water = get_latest_water(db)
    except OperationalError:
        db_ok = False
        device, online, elapsed = None, False, None
        errors, latest_log, latest_event, latest_water = [], None, None, None

    live = state.snapshot()
    if errors:
        level = "error"
    else:
        level = latest_log.level if latest_log else "normal"

    water_level = live["water_level"]
    if water_level is None and latest_water:
        water_level = latest_water.water_level

    return jsonify(
        db_ok=db_ok,
        sortie=live["sortie"],
        online=online,
        last_seen=format_datetime(device.last_seen) if device else "-",
        last_seen_sec=elapsed,
        action=live["action"],
        action_label=labels.ACTION_LABELS.get(live["action"], live["action"]),
        level=level,
        level_label=labels.LEVEL_LABELS[level],
        last_log={"code": latest_log.code, "message": latest_log.message} if latest_log else None,
        unresolved_errors=[{"code": e.code, "message": e.message} for e in errors],
        water_level=water_level,
        latest_event={
            "event_id": latest_event.event_id,
            "detected_at": format_datetime(latest_event.detected_at),
            "temperature": latest_event.temperature,
            "vision_score": latest_event.vision_score,
            "status": latest_event.status,
            "status_label": labels.FIRE_STATUS_LABELS[latest_event.status],
            "url": url_for("fire_detail", event_id=latest_event.event_id),
        } if latest_event else None,
        pending=live["pending"],
    )


@app.post("/api/sortie")
def api_sortie():
    state.start_sortie()
    return jsonify(ok=True, message="출격 명령을 보냈습니다.")


@app.post("/api/control/<cmd>")
def api_control(cmd):
    if cmd not in ("stop", "return", "resume"):
        abort(404)

    message = {"stop": "긴급 정지 명령을 보냈습니다.", "return": "복귀 명령을 보냈습니다.",
               "resume": "재개 명령을 보냈습니다."}[cmd]

    if cmd == "resume":
        with SessionLocal() as db:
            errors = get_unresolved_errors(db)
            if errors:
                codes = ", ".join(e.code or f"#{e.log_id}" for e in errors)
                for e in errors:
                    e.resolved_at = func.now()
                db.add(StatusLog(level="normal", code="MANUAL_RESOLVED",
                                 message=f"관리자 수동 해제: {codes}"[:100]))
                db.add(StatusLog(level="normal", code="PATROL_RESUME", message="관리자 명령으로 순찰 재개"))
                db.commit()
                message = f"에러({codes})를 해제하고 재개 명령을 보냈습니다."

    state.push_command(cmd)
    return jsonify(ok=True, message=message)


if __name__ == "__main__":
    app.run(host=config.SERVER_HOST, port=config.SERVER_PORT, debug=config.DEBUG)
