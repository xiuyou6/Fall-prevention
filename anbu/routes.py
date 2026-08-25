"""Vue 前端使用的本地 JSON API。"""

from __future__ import annotations

from datetime import datetime
from functools import wraps
from pathlib import Path

import cv2
import numpy as np
from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    g,
    jsonify,
    request,
    send_file,
    session,
)
from flask_wtf.csrf import generate_csrf
from sqlalchemy import desc
from uuid import uuid4

from .extensions import csrf, db
from .models import (
    Alert,
    BehaviorEvent,
    Contact,
    DailyCheckin,
    Elder,
    ElderAccount,
    FamilyAssignment,
    EnvironmentCheck,
    Intervention,
    MonitorSession,
    Notification,
    RiskAssessment,
    User,
    VideoJob,
    now,
)
from .reports import build_events_csv, build_risk_pdf
from .services import analyze_live_frame, persist_assessment, serialize_assessment, stop_live_analyzer

web = Blueprint("web", __name__)
SCENES = ("客厅", "卧室", "卫生间")


def api(data: object = {}, message: str = "ok", status: int = 200) -> Response:
    code = "200" if 200 <= status < 300 else str(status)
    return jsonify(code=code, message=message, data=data), status


@web.before_app_request
def load_user() -> None:
    user = db.session.get(User, session.get("user_id")) if session.get("user_id") else None
    if user is not None and not user.is_active:
        session.clear()
        user = None
    g.user = user


def api_login_required(view):
    """Cookie-session guard for JSON routes; never redirect an SPA request to HTML."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return api({}, "请先登录", 401)
        return view(*args, **kwargs)

    return wrapped


def api_role_required(*roles: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return api({}, "请先登录", 401)
            if g.user.role not in roles:
                return api({}, "无权访问此资源", 403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def as_datetime(value) -> str | None:
    return value.isoformat() if value else None


def serialize_user(user: User) -> dict[str, str | None]:
    account = db.session.query(ElderAccount).filter_by(user_id=user.id).first() if user.role == "elder" else None
    return {
        "userId": str(user.id),
        "username": user.username,
        "displayName": user.display_name,
        "role": user.role,
        "elderId": str(account.elder_id) if account else None,
    }


def serialize_elder(elder: Elder, assessment: RiskAssessment | None = None) -> dict:
    return {
        "elderId": str(elder.id),
        "name": elder.name,
        "birthYear": elder.birth_year,
        "priorFalls": elder.prior_falls,
        "mobilityLevel": elder.mobility_level,
        "assistiveDevice": elder.assistive_device,
        "consentGranted": elder.consent_granted,
        "latestRisk": None
        if assessment is None
        else {
            "assessmentId": str(assessment.id),
            "scene": assessment.scene,
            "score": assessment.score,
            "level": assessment.level,
            "reasons": assessment.reasons,
            "createdAt": as_datetime(assessment.created_at),
        },
    }


def serialize_alert(alert: Alert, elder: Elder) -> dict:
    return {
        "alertId": str(alert.id),
        "elderId": str(alert.elder_id),
        "elderName": elder.name,
        "kind": alert.kind,
        "status": alert.status,
        "message": alert.message,
        "createdAt": as_datetime(alert.created_at),
        "responseDeadline": as_datetime(alert.response_deadline),
    }


def serialize_contact(contact: Contact) -> dict:
    """将紧急联系人映射为稳定 JSON 契约。"""
    return {
        "contactId": str(contact.id),
        "elderId": str(contact.elder_id),
        "name": contact.name,
        "email": contact.email,
        "phone": contact.phone,
        "priority": contact.priority,
    }


def serialize_behavior_event(item: BehaviorEvent) -> dict:
    """将行为事件映射为前端展示结构。"""
    return {
        "behaviorEventId": str(item.id),
        "elderId": str(item.elder_id),
        "scene": item.scene,
        "eventType": item.event_type,
        "severity": item.severity,
        "confidence": item.confidence,
        "score": item.score,
        "evidence": item.evidence,
        "source": item.source,
        "startedAt": as_datetime(item.started_at),
        "endedAt": as_datetime(item.ended_at),
    }


def elder_for_user(user: User) -> Elder | None:
    account = db.session.query(ElderAccount).filter_by(user_id=user.id).first()
    return db.session.get(Elder, account.elder_id) if account else None


def accessible_elder_ids() -> list[int]:
    if g.user.role == "admin":
        return [item.id for item in db.session.query(Elder).all()]
    if g.user.role == "elder":
        elder = elder_for_user(g.user)
        return [elder.id] if elder else []
    return [item.elder_id for item in db.session.query(FamilyAssignment).filter_by(user_id=g.user.id)]


def require_elder_access(elder_id: int) -> Elder:
    elder = elder_or_404(elder_id)
    if g.user.role == "admin":
        return elder
    if elder_id not in accessible_elder_ids():
        abort(403)
    return elder


def elder_or_404(elder_id: int) -> Elder:
    elder = db.session.get(Elder, elder_id)
    if elder is None:
        abort(404)
    return elder


@web.route("/api/<path:_path>", methods=["OPTIONS"])
def api_options(_path: str):
    """Browser preflight response; CORS headers are attached by the app factory."""
    return "", 204


@web.get("/api/csrf")
def api_csrf():
    return api({"csrfToken": generate_csrf()})


@web.post("/api/auth/login")
@csrf.exempt
def api_login():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    if not username or not password:
        return api({}, "请输入账号和密码", 400)
    user = db.session.query(User).filter_by(username=username, is_active=True).first()
    if user is None or not user.verify_password(password):
        return api({}, "账号或密码错误", 401)
    session.clear()
    session["user_id"] = user.id
    return api({"user": serialize_user(user), "csrfToken": generate_csrf()})


@web.post("/api/auth/logout")
@api_login_required
def api_logout():
    session.clear()
    return api({})


@web.get("/api/auth/me")
@api_login_required
def api_me():
    return api({"user": serialize_user(g.user), "csrfToken": generate_csrf()})


@web.get("/api/dashboard")
@api_role_required("admin", "family")
def api_dashboard():
    elder_ids = accessible_elder_ids()
    elders = db.session.query(Elder).filter(Elder.id.in_(elder_ids)).order_by(Elder.name).all()
    assessments = {
        elder.id: db.session.query(RiskAssessment)
        .filter_by(elder_id=elder.id)
        .order_by(desc(RiskAssessment.created_at))
        .first()
        for elder in elders
    }
    alerts = (
        db.session.query(Alert)
        .filter(Alert.elder_id.in_(elder_ids), Alert.status.in_(["pending", "confirmed", "processing"]))
        .order_by(desc(Alert.created_at))
        .limit(20)
        .all()
    )
    elder_map = {elder.id: elder for elder in elders}
    scores = [item.score for item in assessments.values() if item and item.score is not None]
    recent_assessments = (
        db.session.query(RiskAssessment)
        .filter(RiskAssessment.elder_id.in_(elder_ids))
        .order_by(desc(RiskAssessment.created_at))
        .limit(30)
        .all()
    )
    recent_assessments.reverse()
    behavior_rows = db.session.query(BehaviorEvent).filter(BehaviorEvent.elder_id.in_(elder_ids)).all()
    behavior_counts: dict[str, int] = {}
    for item in behavior_rows:
        behavior_counts[item.event_type] = behavior_counts.get(item.event_type, 0) + 1
    scene_stats = {
        scene: {
            "count": len(rows),
            "averageScore": round(sum(float(item.score or 0) for item in rows) / len(rows), 1) if rows else None,
        }
        for scene in SCENES
        for rows in [[item for item in recent_assessments if item.scene == scene]]
    }
    return api(
        {
            "elders": [serialize_elder(elder, assessments[elder.id]) for elder in elders],
            "alerts": [serialize_alert(item, elder_map[item.elder_id]) for item in alerts],
            "riskTrend": [
                {"assessmentId": str(item.id), "score": item.score, "level": item.level, "scene": item.scene, "createdAt": as_datetime(item.created_at)}
                for item in recent_assessments
            ],
            "sceneStats": scene_stats,
            "behaviorEventCounts": behavior_counts,
            "summary": {
                "elderCount": len(elders),
                "highRiskCount": sum(1 for item in assessments.values() if item and item.level == "high"),
                "mediumRiskCount": sum(1 for item in assessments.values() if item and item.level == "medium"),
                "averageRiskScore": round(sum(scores) / len(scores), 1) if scores else None,
            },
        }
    )


@web.get("/api/elders")
@api_role_required("admin", "family")
def api_elders():
    elders = db.session.query(Elder).filter(Elder.id.in_(accessible_elder_ids())).order_by(Elder.name).all()
    payload = []
    for elder in elders:
        assessment = (
            db.session.query(RiskAssessment)
            .filter_by(elder_id=elder.id)
            .order_by(desc(RiskAssessment.created_at))
            .first()
        )
        payload.append(serialize_elder(elder, assessment))
    return api(payload)


@web.post("/api/elders")
@api_role_required("admin")
def api_create_elder():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    if not name:
        return api({}, "请填写老人姓名", 400)
    birth_year = payload.get("birthYear")
    if birth_year is not None and (not isinstance(birth_year, int) or birth_year < 1900 or birth_year > 2026):
        return api({}, "出生年份不正确", 400)
    elder = Elder(
        name=name,
        birth_year=birth_year,
        prior_falls=bool(payload.get("priorFalls", False)),
        mobility_level=str(payload.get("mobilityLevel", "independent")),
        assistive_device=str(payload.get("assistiveDevice", "")).strip() or None,
        consent_granted=bool(payload.get("consentGranted", False)),
        consent_at=now() if payload.get("consentGranted") else None,
    )
    db.session.add(elder)
    db.session.commit()
    return api(serialize_elder(elder), "老人档案已创建", 201)


@web.patch("/api/elders/<int:elder_id>")
@api_role_required("admin")
def api_update_elder(elder_id: int):
    elder = elder_or_404(elder_id)
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", elder.name)).strip()
    if not name:
        return api({}, "请填写老人姓名", 400)
    elder.name = name
    if "birthYear" in payload:
        value = payload["birthYear"]
        if value is not None and (not isinstance(value, int) or not 1900 <= value <= 2026):
            return api({}, "出生年份不正确", 400)
        elder.birth_year = value
    for key, field in (("priorFalls", "prior_falls"), ("mobilityLevel", "mobility_level"), ("assistiveDevice", "assistive_device")):
        if key in payload:
            setattr(elder, field, bool(payload[key]) if key == "priorFalls" else str(payload[key]).strip() or None)
    if "consentGranted" in payload:
        elder.consent_granted = bool(payload["consentGranted"])
        elder.consent_at = now() if elder.consent_granted else None
    db.session.commit()
    return api(serialize_elder(elder), "老人档案已更新")


@web.delete("/api/elders/<int:elder_id>")
@api_role_required("admin")
def api_delete_elder(elder_id: int):
    elder = elder_or_404(elder_id)
    if db.session.query(Alert).filter_by(elder_id=elder_id).first() or db.session.query(MonitorSession).filter_by(elder_id=elder_id).first():
        return api({}, "该老人已有监测或告警记录，不能删除；请保留档案以保障审计完整性", 409)
    db.session.query(Contact).filter_by(elder_id=elder_id).delete()
    db.session.query(EnvironmentCheck).filter_by(elder_id=elder_id).delete()
    db.session.query(DailyCheckin).filter_by(elder_id=elder_id).delete()
    db.session.query(FamilyAssignment).filter_by(elder_id=elder_id).delete()
    account = db.session.query(ElderAccount).filter_by(elder_id=elder_id).first()
    if account:
        db.session.delete(db.session.get(User, account.user_id))
        db.session.delete(account)
    db.session.delete(elder)
    db.session.commit()
    return api({}, "老人档案已删除")


@web.route("/api/elders/<int:elder_id>/contacts", methods=["GET", "POST"])
@api_role_required("admin", "family", "elder")
def api_contacts(elder_id: int):
    """查询或创建紧急联系人。"""
    require_elder_access(elder_id)
    if request.method == "GET":
        contacts = db.session.query(Contact).filter_by(elder_id=elder_id).order_by(Contact.priority, Contact.id).all()
        return api([serialize_contact(item) for item in contacts])
    if g.user.role == "elder":
        return api({}, "老人账号只能查看紧急联系人", 403)
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip()
    phone = str(payload.get("phone", "")).strip() or None
    try:
        priority = max(1, min(99, int(payload.get("priority", 1))))
    except (TypeError, ValueError):
        return api({}, "联系人优先级必须是数字", 400)
    if not name or "@" not in email:
        return api({}, "请填写联系人姓名和有效邮箱", 400)
    item = Contact(elder_id=elder_id, name=name, email=email, phone=phone, priority=priority)
    db.session.add(item)
    db.session.commit()
    return api(serialize_contact(item), "紧急联系人已创建", 201)


@web.route("/api/elders/<int:elder_id>/contacts/<int:contact_id>", methods=["PATCH", "DELETE"])
@api_role_required("admin", "family")
def api_contact_detail(elder_id: int, contact_id: int):
    """更新或删除授权老人名下的紧急联系人。"""
    require_elder_access(elder_id)
    item = db.session.get(Contact, contact_id)
    if item is None or item.elder_id != elder_id:
        return api({}, "紧急联系人不存在", 404)
    if request.method == "DELETE":
        db.session.delete(item)
        db.session.commit()
        return api({}, "紧急联系人已删除")
    payload = request.get_json(silent=True) or {}
    if "name" in payload and str(payload["name"]).strip():
        item.name = str(payload["name"]).strip()
    if "email" in payload:
        email = str(payload["email"]).strip()
        if "@" not in email:
            return api({}, "联系人邮箱无效", 400)
        item.email = email
    if "phone" in payload:
        item.phone = str(payload["phone"]).strip() or None
    if "priority" in payload:
        try:
            item.priority = max(1, min(99, int(payload["priority"])))
        except (TypeError, ValueError):
            return api({}, "联系人优先级必须是数字", 400)
    db.session.commit()
    return api(serialize_contact(item), "紧急联系人已更新")


@web.route("/api/elders/<int:elder_id>/environment-checks", methods=["GET", "POST"])
@api_role_required("admin", "family", "elder")
def api_environment_check(elder_id: int):
    elder = require_elder_access(elder_id)
    if request.method == "GET":
        rows = db.session.query(EnvironmentCheck).filter_by(elder_id=elder_id).order_by(desc(EnvironmentCheck.created_at)).limit(100).all()
        return api(
            [
                {
                    "environmentCheckId": str(item.id),
                    "scene": item.scene,
                    "wetFloor": item.wet_floor,
                    "obstacles": item.obstacles,
                    "dimLight": item.dim_light,
                    "clutter": item.clutter,
                    "exposedCables": item.exposed_cables,
                    "missingHandrail": item.missing_handrail,
                    "notes": item.notes,
                    "createdAt": as_datetime(item.created_at),
                }
                for item in rows
            ]
        )
    if g.user.role == "elder":
        return api({}, "老人账号只能查看环境检查", 403)
    payload = request.get_json(silent=True) or {}
    scene = str(payload.get("scene", ""))
    if scene not in SCENES:
        return api({}, "请选择有效场景", 400)
    item = EnvironmentCheck(
        elder_id=elder_id,
        scene=scene,
        notes=str(payload.get("notes", "")).strip() or None,
    )
    item.wet_floor = bool(payload.get("wetFloor"))
    item.obstacles = bool(payload.get("obstacles"))
    item.dim_light = bool(payload.get("dimLight"))
    item.clutter = bool(payload.get("clutter"))
    item.exposed_cables = bool(payload.get("exposedCables"))
    item.missing_handrail = bool(payload.get("missingHandrail"))
    db.session.add(item)
    db.session.flush()
    assessment = persist_assessment(elder, scene, "environment")
    return api({"environmentCheckId": str(item.id), "assessment": serialize_assessment(assessment)}, "环境检查已保存并重新评分", 201)


@web.route("/api/elders/<int:elder_id>/daily-checkins", methods=["GET", "POST"])
@api_role_required("admin", "family", "elder")
def api_daily_checkin(elder_id: int):
    elder = require_elder_access(elder_id)
    if request.method == "GET":
        rows = db.session.query(DailyCheckin).filter_by(elder_id=elder_id).order_by(desc(DailyCheckin.created_at)).limit(100).all()
        return api(
            [
                {
                    "checkinId": str(item.id),
                    "dizziness": item.dizziness,
                    "fatigue": item.fatigue,
                    "sleepQuality": item.sleep_quality,
                    "pain": item.pain,
                    "medicationChanged": item.medication_changed,
                    "createdAt": as_datetime(item.created_at),
                }
                for item in rows
            ]
        )
    payload = request.get_json(silent=True) or {}
    try:
        values = {key: max(0, min(5, int(payload.get(key, default)))) for key, default in (("dizziness", 0), ("fatigue", 0), ("sleepQuality", 5), ("pain", 0))}
    except (TypeError, ValueError):
        return api({}, "问询评分必须在 0 到 5 之间", 400)
    item = DailyCheckin(elder_id=elder_id, dizziness=values["dizziness"], fatigue=values["fatigue"], sleep_quality=values["sleepQuality"], pain=values["pain"], medication_changed=bool(payload.get("medicationChanged")))
    db.session.add(item)
    db.session.flush()
    assessment = persist_assessment(elder, str(payload.get("scene", "客厅")) if str(payload.get("scene", "客厅")) in SCENES else "客厅", "checkin")
    return api({"checkinId": str(item.id), "assessment": serialize_assessment(assessment)}, "每日问询已保存并重新评分", 201)


@web.post("/api/elders/<int:elder_id>/monitor-sessions")
@api_role_required("admin", "family")
def api_create_monitor_session(elder_id: int):
    elder = require_elder_access(elder_id)
    if not elder.consent_granted:
        return api({}, "未取得隐私授权，不能启动监测", 403)
    payload = request.get_json(silent=True) or {}
    scene = str(payload.get("scene", ""))
    if scene not in SCENES:
        return api({}, "请选择有效场景", 400)
    item = MonitorSession(elder_id=elder_id, scene=scene)
    db.session.add(item)
    db.session.commit()
    return api({"monitorSessionId": str(item.id), "status": item.status}, "监测已启动", 201)


@web.post("/api/elders/<int:elder_id>/videos")
@api_role_required("admin", "family")
def api_upload_video(elder_id: int):
    elder = require_elder_access(elder_id)
    if not elder.consent_granted:
        return api({}, "未取得隐私授权，不能上传视频", 403)
    file = request.files.get("video")
    scene = request.form.get("scene", "")
    if scene not in SCENES or file is None or not file.filename:
        return api({}, "请提供场景和视频文件", 400)
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".mp4", ".avi", ".mov", ".mkv"}:
        return api({}, "仅支持 MP4、AVI、MOV 或 MKV 视频", 400)
    destination = Path(current_app.config["UPLOAD_ROOT"]) / f"{elder_id}_{uuid4().hex}{suffix}"
    file.save(destination)
    if destination.stat().st_size > current_app.config["MAX_VIDEO_BYTES"]:
        destination.unlink(missing_ok=True)
        return api({}, "视频文件超过允许大小", 413)
    capture = cv2.VideoCapture(str(destination))
    opened, frame = capture.read()
    capture.release()
    if not opened or frame is None:
        destination.unlink(missing_ok=True)
        return api({}, "文件不是可解码的有效视频", 400)
    job = VideoJob(elder_id=elder_id, scene=scene, file_path=str(destination))
    db.session.add(job)
    db.session.commit()
    return api({"videoJobId": str(job.id), "status": job.status}, "视频已进入分析队列", 201)


@web.get("/api/video-jobs/<int:job_id>")
@api_role_required("admin", "family")
def api_video_job(job_id: int):
    job = db.session.get(VideoJob, job_id)
    if job is None:
        return api({}, "视频任务不存在", 404)
    require_elder_access(job.elder_id)
    assessment = (
        db.session.query(RiskAssessment)
        .filter_by(elder_id=job.elder_id, source="video")
        .filter(RiskAssessment.created_at >= job.created_at)
        .order_by(desc(RiskAssessment.created_at))
        .first()
        if job.status == "succeeded"
        else None
    )
    alert = db.session.query(Alert).filter_by(assessment_id=assessment.id).order_by(desc(Alert.created_at)).first() if assessment else None
    return api(
        {
            "videoJobId": str(job.id),
            "elderId": str(job.elder_id),
            "scene": job.scene,
            "status": job.status,
            "errorMessage": job.error_message,
            "totalFrames": job.total_frames,
            "progressFrames": job.progress_frames,
            "durationSeconds": job.duration_seconds,
            "currentConfidence": job.current_confidence,
            "frameMetrics": job.frame_metrics,
            "createdAt": as_datetime(job.created_at),
            "completedAt": as_datetime(job.completed_at),
            "assessment": serialize_assessment(assessment) if assessment else None,
            "alertId": str(alert.id) if alert else None,
        }
    )


@web.get("/api/video-jobs/<int:job_id>/preview")
@api_role_required("admin", "family")
def api_video_preview(job_id: int):
    """返回已授权本地视频任务的可播放预览流。"""
    job = db.session.get(VideoJob, job_id)
    if job is None:
        return api({}, "视频任务不存在", 404)
    require_elder_access(job.elder_id)

    video_path = Path(job.file_path)
    upload_root = Path(current_app.config["UPLOAD_ROOT"]).resolve()
    try:
        video_path.resolve().relative_to(upload_root)
    except ValueError:
        current_app.logger.warning("视频任务 %s 的文件路径不在上传目录内", job.id)
        return api({}, "视频文件不可访问", 404)
    if not video_path.is_file():
        return api({}, "视频文件已不存在", 404)

    mime_types = {
        ".mp4": "video/mp4",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
    }
    return send_file(video_path, mimetype=mime_types.get(video_path.suffix.lower(), "application/octet-stream"), conditional=True)


@web.get("/api/video-jobs/<int:job_id>/frame")
@api_role_required("admin", "family")
def api_video_frame(job_id: int):
    """提供浏览器不支持原视频编码时的解码帧回退画面。"""
    job = db.session.get(VideoJob, job_id)
    if job is None:
        return api({}, "视频任务不存在", 404)
    require_elder_access(job.elder_id)
    try:
        timestamp = max(0.0, float(request.args.get("time", "0")))
    except ValueError:
        return api({}, "时间参数无效", 400)
    video_path = Path(job.file_path)
    upload_root = Path(current_app.config["UPLOAD_ROOT"]).resolve()
    try:
        video_path.resolve().relative_to(upload_root)
    except ValueError:
        current_app.logger.warning("视频任务 %s 的文件路径不在上传目录内", job.id)
        return api({}, "视频文件不可访问", 404)
    if not video_path.is_file():
        return api({}, "视频文件已不存在", 404)
    capture = cv2.VideoCapture(str(video_path))
    try:
        if not capture.isOpened():
            return api({}, "视频无法解码", 400)
        fps = capture.get(cv2.CAP_PROP_FPS) or 25
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(timestamp * fps))
        readable, frame = capture.read()
        if not readable or frame is None:
            return api({}, "该时间点没有可读取画面", 404)
        encoded, image = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        if not encoded:
            return api({}, "视频画面编码失败", 500)
        return Response(image.tobytes(), mimetype="image/jpeg", headers={"Cache-Control": "no-store"})
    finally:
        capture.release()


@web.get("/api/admin/families")
@api_role_required("admin")
def api_families():
    users = db.session.query(User).filter_by(role="family", is_active=True).order_by(User.display_name).all()
    return api([serialize_user(user) for user in users])


@web.get("/api/admin/family-assignments")
@api_role_required("admin")
def api_family_assignments():
    assignments = db.session.query(FamilyAssignment).all()
    users = {item.id: item for item in db.session.query(User).filter_by(role="family").all()}
    elders = {item.id: item for item in db.session.query(Elder).all()}
    return api([{"userId": str(item.user_id), "familyName": users[item.user_id].display_name, "elderId": str(item.elder_id), "elderName": elders[item.elder_id].name, "consentGranted": elders[item.elder_id].consent_granted} for item in assignments if item.user_id in users and item.elder_id in elders])


@web.post("/api/admin/family-assignments")
@api_role_required("admin")
def api_create_family_assignment():
    payload = request.get_json(silent=True) or {}
    try:
        user_id, elder_id = int(payload.get("userId")), int(payload.get("elderId"))
    except (TypeError, ValueError):
        return api({}, "请选择家属和老人", 400)
    user, elder = db.session.get(User, user_id), db.session.get(Elder, elder_id)
    if user is None or user.role != "family" or elder is None:
        return api({}, "家属或老人不存在", 404)
    if db.session.get(FamilyAssignment, (user_id, elder_id)) is not None:
        return api({}, "该绑定已存在", 409)
    db.session.add(FamilyAssignment(user_id=user_id, elder_id=elder_id))
    db.session.commit()
    return api({"userId": str(user_id), "familyName": user.display_name, "elderId": str(elder_id), "elderName": elder.name, "consentGranted": elder.consent_granted}, "绑定已创建", 201)


@web.delete("/api/admin/family-assignments/<int:user_id>/<int:elder_id>")
@api_role_required("admin")
def api_delete_family_assignment(user_id: int, elder_id: int):
    item = db.session.get(FamilyAssignment, (user_id, elder_id))
    if item is None:
        return api({}, "授权绑定不存在", 404)
    db.session.delete(item)
    db.session.commit()
    return api({}, "授权绑定已解除")


@web.route("/api/admin/users", methods=["GET", "POST"])
@api_role_required("admin")
def api_users():
    if request.method == "GET":
        users = db.session.query(User).order_by(User.role, User.username).all()
        links = {item.user_id: item.elder_id for item in db.session.query(ElderAccount).all()}
        return api(
            [
                {
                    **serialize_user(user),
                    "isActive": user.is_active,
                    "elderId": str(links[user.id]) if user.id in links else None,
                }
                for user in users
            ]
        )
    payload = request.get_json(silent=True) or {}
    username, display_name, password = (str(payload.get(key, "")).strip() for key in ("username", "displayName", "password"))
    role = str(payload.get("role", ""))
    if role not in {"admin", "family", "elder"}:
        return api({}, "请选择有效账号角色", 400)
    if len(username) < 3 or not display_name or len(password) < 8:
        return api({}, "账号至少 3 位，姓名不能为空，密码至少 8 位", 400)
    if db.session.query(User).filter_by(username=username).first():
        return api({}, "登录账号已存在", 409)
    elder = None
    if role == "elder":
        try:
            elder = db.session.get(Elder, int(payload.get("elderId")))
        except (TypeError, ValueError):
            elder = None
        if elder is None:
            return api({}, "老人账号必须绑定有效老人档案", 400)
        if db.session.query(ElderAccount).filter_by(elder_id=elder.id).first() is not None:
            return api({}, "该老人档案已有登录账号", 409)
    user = User(username=username, display_name=display_name, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    if elder is not None:
        db.session.add(ElderAccount(user_id=user.id, elder_id=elder.id))
    db.session.commit()
    return api(
        {
            **serialize_user(user),
            "isActive": user.is_active,
            "elderId": str(elder.id) if elder else None,
        },
        "账号已创建",
        201,
    )


@web.patch("/api/admin/users/<int:user_id>")
@api_role_required("admin")
def api_update_user(user_id: int):
    user = db.session.get(User, user_id)
    if user is None:
        return api({}, "账号不存在", 404)
    payload = request.get_json(silent=True) or {}
    if "displayName" in payload and str(payload["displayName"]).strip():
        user.display_name = str(payload["displayName"]).strip()
    if "isActive" in payload:
        next_active = bool(payload["isActive"])
        if not next_active and user.id == g.user.id:
            return api({}, "不能停用当前登录账号", 409)
        if not next_active and user.role == "admin":
            active_admins = db.session.query(User).filter_by(role="admin", is_active=True).count()
            if active_admins <= 1:
                return api({}, "系统必须保留至少一个有效管理员", 409)
        user.is_active = next_active
    if payload.get("password"):
        if len(str(payload["password"])) < 8:
            return api({}, "密码至少 8 位", 400)
        user.set_password(str(payload["password"]))
    db.session.commit()
    return api({**serialize_user(user), "isActive": user.is_active}, "账号已更新")


@web.get("/api/alerts")
@api_role_required("admin", "family", "elder")
def api_alerts():
    if g.user.role == "elder":
        elder = elder_for_user(g.user)
        elder_ids = [elder.id] if elder else []
    else:
        elder_ids = accessible_elder_ids()
    query = db.session.query(Alert).filter(Alert.elder_id.in_(elder_ids))
    status = request.args.get("status", "").strip()
    if status:
        statuses = [item for item in status.split(",") if item in {"pending", "confirmed", "processing", "closed", "false_positive"}]
        if not statuses:
            return api({}, "告警状态参数无效", 400)
        query = query.filter(Alert.status.in_(statuses))
    updated_after = request.args.get("updatedAfter", "").strip()
    if updated_after:
        try:
            query = query.filter(Alert.created_at > datetime.fromisoformat(updated_after))
        except ValueError:
            return api({}, "updatedAfter 必须是 ISO 8601 时间", 400)
    entries = query.order_by(desc(Alert.created_at)).limit(200).all()
    elder_map = {item.id: item for item in db.session.query(Elder).filter(Elder.id.in_(elder_ids)).all()}
    return api([serialize_alert(item, elder_map[item.elder_id]) for item in entries])


@web.patch("/api/alerts/<int:alert_id>")
@api_role_required("admin", "family", "elder")
def api_update_alert(alert_id: int):
    alert = db.session.get(Alert, alert_id)
    if alert is None:
        return api({}, "告警不存在", 404)
    if g.user.role == "elder":
        linked = elder_for_user(g.user)
        if linked is None or linked.id != alert.elder_id:
            return api({}, "无权处理此告警", 403)
    elif alert.elder_id not in accessible_elder_ids():
        return api({}, "无权处理此告警", 403)
    payload = request.get_json(silent=True) or {}
    action = payload.get("action")
    mapping = {"confirm": "confirmed", "false": "false_positive", "process": "processing", "close": "closed", "safe": "false_positive", "help": "confirmed"}
    if action not in mapping:
        return api({}, "无效的告警操作", 400)
    if g.user.role == "elder" and action not in {"safe", "help"}:
        return api({}, "老人账号只能选择我没事或需要帮助", 403)
    allowed = {
        "pending": {"confirmed", "false_positive"},
        "confirmed": {"processing"},
        "processing": {"closed"},
        "closed": set(),
        "false_positive": set(),
    }
    target = mapping[action]
    if alert.status == target:
        return api(serialize_alert(alert, elder_or_404(alert.elder_id)))
    if target not in allowed.get(alert.status, set()):
        return api({}, f"不能从 {alert.status} 转换为 {target}", 409)
    alert.status = target
    alert.closed_at = now() if target in {"closed", "false_positive"} else None
    db.session.add(Intervention(alert_id=alert.id, action=action, note=str(payload.get("note", "")).strip() or None))
    if action == "help":
        elder = elder_or_404(alert.elder_id)
        subject = "【安步守护】老人主动请求帮助"
        for contact in db.session.query(Contact).filter_by(elder_id=elder.id).order_by(Contact.priority):
            exists = db.session.query(Notification).filter_by(alert_id=alert.id, recipient=contact.email, subject=subject).first()
            if exists is None:
                db.session.add(
                    Notification(
                        alert_id=alert.id,
                        recipient=contact.email,
                        subject=subject,
                        body=f"{elder.name} 已在老人端选择“需要帮助”，请立即联系或前往查看。",
                    )
                )
    db.session.commit()
    return api(serialize_alert(alert, elder_or_404(alert.elder_id)))


@web.get("/api/alerts/<int:alert_id>")
@api_role_required("admin", "family", "elder")
def api_alert_detail(alert_id: int):
    """返回告警及完整干预记录。"""
    alert = db.session.get(Alert, alert_id)
    if alert is None:
        return api({}, "告警不存在", 404)
    require_elder_access(alert.elder_id)
    interventions = db.session.query(Intervention).filter_by(alert_id=alert.id).order_by(Intervention.created_at).all()
    return api(
        {
            **serialize_alert(alert, elder_or_404(alert.elder_id)),
            "interventions": [
                {
                    "interventionId": str(item.id),
                    "action": item.action,
                    "note": item.note,
                    "createdAt": as_datetime(item.created_at),
                }
                for item in interventions
            ],
        }
    )


@web.post("/api/monitor-sessions/<int:monitor_id>/frames")
@api_role_required("admin", "family")
def submit_frame(monitor_id: int):
    monitor_item = db.session.get(MonitorSession, monitor_id)
    if monitor_item is None or monitor_item.status != "active":
        return api({}, "监测会话不存在或已停止", 404)
    require_elder_access(monitor_item.elder_id)
    upload = request.files.get("frame")
    if upload is None:
        return api({}, "缺少摄像头帧", 400)
    image = cv2.imdecode(np.frombuffer(upload.read(), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return api({}, "摄像头帧无效", 400)
    return api(analyze_live_frame(monitor_item, image))


@web.post("/api/monitor-sessions/<int:monitor_id>/stop")
@api_role_required("admin", "family")
def stop_monitor(monitor_id: int):
    item = db.session.get(MonitorSession, monitor_id)
    if item is None:
        return api({}, "监测会话不存在", 404)
    require_elder_access(item.elder_id)
    item.status = "stopped"
    item.stopped_at = now()
    stop_live_analyzer(item.id)
    db.session.commit()
    return api({"sessionId": str(item.id), "status": item.status})


@web.get("/api/elders/<int:elder_id>/risk-trend")
@api_role_required("admin", "family")
def api_risk_trend(elder_id: int):
    """返回风险趋势、场景分布和行为事件统计。"""
    require_elder_access(elder_id)
    assessments = db.session.query(RiskAssessment).filter_by(elder_id=elder_id).order_by(RiskAssessment.created_at).limit(500).all()
    events = db.session.query(BehaviorEvent).filter_by(elder_id=elder_id).order_by(desc(BehaviorEvent.created_at)).limit(200).all()
    scenes = {
        scene: {
            "assessmentCount": len(rows),
            "averageScore": round(sum(float(item.score or 0) for item in rows) / len(rows), 1) if rows else None,
            "highRiskCount": sum(item.level == "high" for item in rows),
        }
        for scene in SCENES
        for rows in [[item for item in assessments if item.scene == scene]]
    }
    event_counts: dict[str, int] = {}
    for item in events:
        event_counts[item.event_type] = event_counts.get(item.event_type, 0) + 1
    return api(
        {
            "assessments": [
                {
                    **serialize_assessment(item),
                    "scene": item.scene,
                    "source": item.source,
                }
                for item in assessments
            ],
            "scenes": scenes,
            "behaviorEventCounts": event_counts,
        }
    )


@web.get("/api/elders/<int:elder_id>/behavior-events")
@api_role_required("admin", "family")
def api_behavior_events(elder_id: int):
    """返回授权老人最近的派生行为事件。"""
    require_elder_access(elder_id)
    rows = db.session.query(BehaviorEvent).filter_by(elder_id=elder_id).order_by(desc(BehaviorEvent.created_at)).limit(200).all()
    return api([serialize_behavior_event(item) for item in rows])


@web.get("/api/elders/<int:elder_id>/reports/risk.pdf")
@api_role_required("admin", "family")
def api_risk_pdf(elder_id: int):
    """导出完整风险与事件 PDF。"""
    require_elder_access(elder_id)
    destination = Path(current_app.config["UPLOAD_ROOT"]) / "reports" / f"elder-{elder_id}-risk.pdf"
    return send_file(build_risk_pdf(elder_id, destination), as_attachment=True, download_name=f"安步守护-老人{elder_id}-风险报告.pdf", mimetype="application/pdf")


@web.get("/api/elders/<int:elder_id>/reports/events.csv")
@api_role_required("admin", "family")
def api_events_csv(elder_id: int):
    """导出风险、行为、告警和干预 CSV。"""
    require_elder_access(elder_id)
    destination = Path(current_app.config["UPLOAD_ROOT"]) / "reports" / f"elder-{elder_id}-events.csv"
    return send_file(build_events_csv(elder_id, destination), as_attachment=True, download_name=f"安步守护-老人{elder_id}-事件明细.csv", mimetype="text/csv; charset=utf-8")


@web.get("/api/admin/system-status")
@api_role_required("admin")
def api_system_status():
    """返回不含凭据的本地运行诊断信息。"""
    worker = current_app.extensions.get("anbu_background_worker", {})
    thread = worker.get("thread") if isinstance(worker, dict) else None
    return api(
        {
            "fallModelReady": current_app.config["MODEL_PATH"].is_file(),
            "poseModelReady": current_app.config["POSE_MODEL_PATH"].is_file(),
            "smtpConfigured": bool(current_app.config["SMTP_HOST"] and current_app.config["SMTP_FROM"]),
            "backgroundWorkerRunning": bool(thread and thread.is_alive()),
            "database": "SQLite",
            "timezone": current_app.config["APP_TIMEZONE"],
            "alertResponseSeconds": current_app.config["ALERT_RESPONSE_SECONDS"],
            "alertPollSeconds": current_app.config["ALERT_POLL_SECONDS"],
            "videoSources": ["browserCamera", "localUpload"],
            "riskFormulaVersion": current_app.config["RISK_FORMULA_VERSION"],
        }
    )
