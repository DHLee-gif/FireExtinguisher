import datetime
import os

from flask import Blueprint, jsonify, request
from sqlalchemy import func
from werkzeug.utils import secure_filename

import config
import state
from db import SessionLocal
from labels import ACTION_LABELS
from models import Device, FireEvent, FireImage, SprayLog, StatusLog, WaterLog

bp = Blueprint("rc_api", __name__, url_prefix="/api")

FIRE_STATUSES = ("detected", "spraying", "extinguished", "failed")
FINAL_STATUSES = ("extinguished", "failed")
LEVELS = ("normal", "warning", "error")
WATER_ACTIONS = ("low", "homing", "refilled", "homing_failed")


def payload():
    return request.get_json(silent=True) or request.form


def to_float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def to_int(value):
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def error(message, code=400):
    return jsonify(ok=False, error=message), code


def check_image(file):
    if file is None or not file.filename:
        return None, "image 파일이 필요합니다."
    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
    if ext not in config.ALLOWED_IMAGE_EXT:
        return None, f"허용되지 않는 확장자입니다: {ext or '(없음)'}"
    return ext, None


def save_image(file, ext, event_id, img_type):
    os.makedirs(config.UPLOAD_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"fire{event_id}_{img_type}_{stamp}{ext}"
    file.save(os.path.join(config.UPLOAD_DIR, filename))
    return f"{config.UPLOAD_SUBDIR}/{filename}"


@bp.post("/heartbeat")
def heartbeat():
    data = payload()
    action = data.get("action") or None
    if action and action not in ACTION_LABELS:
        return error(f"알 수 없는 action: {action}")
    water_level = to_float(data.get("water_level"))

    state.update_from_heartbeat(action, water_level)

    with SessionLocal() as db:
        device = db.get(Device, config.DEVICE_ID)
        if device is None:
            return error("device 행이 없습니다. seed.py 를 먼저 실행하세요.", 500)
        device.last_seen = func.now()
        db.commit()

    return jsonify(ok=True)


@bp.get("/command")
def command():
    return jsonify(command=state.pop_command())


@bp.post("/fire")
def create_fire():
    data = request.form
    file = request.files.get("image")
    ext, err = check_image(file)
    if err:
        return error(err)

    with SessionLocal() as db:
        event = FireEvent(
            temperature=to_float(data.get("temperature")),
            vision_score=to_float(data.get("vision_score")),
        )
        db.add(event)
        db.flush()
        path = save_image(file, ext, event.event_id, "before")
        db.add(FireImage(event_id=event.event_id, img_type="before", file_path=path))
        db.commit()
        return jsonify(ok=True, event_id=event.event_id), 201


@bp.post("/fire/<int:event_id>/spray")
def add_spray(event_id):
    data = payload()
    with SessionLocal() as db:
        event = db.get(FireEvent, event_id)
        if event is None:
            return error("fire_event 가 없습니다.", 404)
        spray = SprayLog(
            event_id=event_id,
            duration_ms=to_int(data.get("duration_ms")),
            temp_after=to_float(data.get("temp_after")),
        )
        db.add(spray)
        if event.status == "detected":
            event.status = "spraying"
        db.commit()
        return jsonify(ok=True, spray_id=spray.spray_id), 201


@bp.post("/fire/<int:event_id>/image")
def add_after_image(event_id):
    file = request.files.get("image")
    ext, err = check_image(file)
    if err:
        return error(err)

    with SessionLocal() as db:
        if db.get(FireEvent, event_id) is None:
            return error("fire_event 가 없습니다.", 404)
        path = save_image(file, ext, event_id, "after")
        image = FireImage(event_id=event_id, img_type="after", file_path=path)
        db.add(image)
        db.commit()
        return jsonify(ok=True, image_id=image.image_id), 201


@bp.put("/fire/<int:event_id>")
def update_fire(event_id):
    data = payload()
    status = data.get("status")
    if status not in FIRE_STATUSES:
        return error(f"status 는 {FIRE_STATUSES} 중 하나여야 합니다.")

    closed_at = None
    if data.get("closed_at"):
        try:
            closed_at = datetime.datetime.fromisoformat(data["closed_at"])
        except ValueError:
            return error("closed_at 은 ISO 형식(YYYY-MM-DD HH:MM:SS)이어야 합니다.")

    with SessionLocal() as db:
        event = db.get(FireEvent, event_id)
        if event is None:
            return error("fire_event 가 없습니다.", 404)
        event.status = status
        if closed_at:
            event.closed_at = closed_at
        elif status in FINAL_STATUSES:
            event.closed_at = func.now()
        db.commit()
        return jsonify(ok=True)


@bp.post("/status")
def add_status():
    data = payload()
    level = data.get("level")
    if level not in LEVELS:
        return error(f"level 은 {LEVELS} 중 하나여야 합니다.")

    with SessionLocal() as db:
        log = StatusLog(
            level=level,
            code=(data.get("code") or None) and data["code"][:30],
            message=(data.get("message") or None) and data["message"][:100],
        )
        db.add(log)
        db.commit()
        return jsonify(ok=True, log_id=log.log_id), 201


@bp.post("/water")
def add_water():
    data = payload()
    action = data.get("action") or None
    if action and action not in WATER_ACTIONS:
        return error(f"action 은 {WATER_ACTIONS} 중 하나여야 합니다.")
    water_level = to_float(data.get("water_level"))

    with SessionLocal() as db:
        log = WaterLog(water_level=water_level, action=action)
        db.add(log)
        db.commit()

    state.update_water(water_level)
    return jsonify(ok=True, log_id=log.log_id), 201
