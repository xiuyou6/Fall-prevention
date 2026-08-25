"""Business rules, local inference adapters and background processing."""

from __future__ import annotations

import atexit
import smtplib
import shutil
import tempfile
import threading
from datetime import timedelta
from email.message import EmailMessage
from pathlib import Path

import cv2
import numpy as np
from flask import current_app
from sqlalchemy import desc, text

from .behavior import BehaviorAnalyzer, BehaviorResult, PoseSample
from .extensions import db
from .models import (
    Alert,
    BehaviorEvent,
    Contact,
    DailyCheckin,
    Elder,
    EnvironmentCheck,
    Intervention,
    MonitorSession,
    Notification,
    RiskAssessment,
    User,
    VideoJob,
    now,
)

DISCLAIMER = "本结果仅用于安全辅助提示，不构成医疗诊断或自动限制活动的依据。"
_model = None
_pose_model = None
_pose_lock = threading.Lock()
_live_analyzers: dict[int, BehaviorAnalyzer] = {}


def _close_pose_model() -> None:
    """在解释器模块卸载前主动关闭 MediaPipe 原生资源。"""
    global _pose_model
    if _pose_model is not None:
        try:
            _pose_model.close()
        finally:
            _pose_model = None


atexit.register(_close_pose_model)


def bootstrap_database() -> None:
    db.create_all()
    # SQLite 的 create_all 不会给已存在的表补列；为本地单机升级补齐视频播放所需进度与逐帧数据。
    if db.engine.dialect.name == "sqlite":
        video_job_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(video_jobs)"))}
        pending_columns = {
            "total_frames": "INTEGER NOT NULL DEFAULT 0",
            "progress_frames": "INTEGER NOT NULL DEFAULT 0",
            "duration_seconds": "FLOAT",
            "current_confidence": "FLOAT",
            "frame_metrics": "JSON NOT NULL DEFAULT '[]'",
        }
        for column, definition in pending_columns.items():
            if column not in video_job_columns:
                db.session.execute(text(f"ALTER TABLE video_jobs ADD COLUMN {column} {definition}"))
    db.session.execute(text("PRAGMA journal_mode=WAL"))
    if db.session.query(User).filter_by(username="admin").first() is None:
        admin = User(username="admin", display_name="系统管理员", role="admin")
        admin.set_password(current_app.config["BOOTSTRAP_ADMIN_PASSWORD"])
        db.session.add(admin)
    else:
        admin = db.session.query(User).filter_by(username="admin").first()
        # Seamlessly migrate only the former documented development password.
        if admin and admin.verify_password("ChangeMe123!"):
            admin.set_password(current_app.config["BOOTSTRAP_ADMIN_PASSWORD"])
        if current_app.config["APP_ENV"] == "production" and admin and admin.verify_password("123456"):
            admin.set_password(current_app.config["BOOTSTRAP_ADMIN_PASSWORD"])
    db.session.commit()


def risk_label(score: float) -> str:
    return "high" if score >= 70 else "medium" if score >= 40 else "low"


def score_risk(
    elder: Elder,
    scene: str,
    behavior: dict[str, float] | None = None,
    data_quality: dict | None = None,
) -> tuple[float, list[str], dict]:
    """按个人20、行为35、环境25、时间20计算可解释风险分。"""
    behavior = behavior or {}
    reasons: list[str] = []
    base = 0.0
    if elder.prior_falls:
        base += 5
        reasons.append("有既往跌倒史")
    if elder.mobility_level in {"limited", "assisted"}:
        base += 5
        reasons.append("行动能力需要额外支持")
    if elder.assistive_device:
        base += 3
        reasons.append("日常使用辅助器具")
    if elder.birth_year and 2026 - elder.birth_year >= 80:
        base += 2
        reasons.append("高龄需要加强防护")

    environment = (
        db.session.query(EnvironmentCheck)
        .filter_by(elder_id=elder.id, scene=scene)
        .order_by(desc(EnvironmentCheck.created_at))
        .first()
    )
    environment_points = 0.0
    fixes: list[str] = []
    if environment:
        checks = [
            (environment.wet_floor, "地面湿滑", "保持地面干燥"),
            (environment.obstacles, "通道有障碍物", "清理通行通道"),
            (environment.dim_light, "照明不足", "打开照明或安装夜灯"),
            (environment.clutter, "现场杂物较多", "整理地面杂物"),
            (environment.exposed_cables, "有外露电线", "固定或收纳电线"),
            (environment.missing_handrail, "缺少扶手", "在关键位置加装扶手"),
        ]
        for active, issue, fix in checks:
            if active:
                environment_points += 8.4
                reasons.append(issue)
                fixes.append(fix)
        environment_points = min(25.0, environment_points)

    checkin = (
        db.session.query(DailyCheckin).filter_by(elder_id=elder.id).order_by(desc(DailyCheckin.created_at)).first()
    )
    subjective = 0.0
    if checkin:
        subjective += min(checkin.dizziness, 5) * 0.7
        subjective += min(checkin.fatigue, 5) * 0.5
        subjective += max(0, 3 - checkin.sleep_quality) * 0.7
        subjective += min(checkin.pain, 5) * 0.4
        subjective += 1 if checkin.medication_changed else 0
        if subjective >= 4:
            reasons.append("今日主观状态提示需加强看护")

    behavior_points = min(
        35.0,
        sum(float(behavior.get(key, 0)) for key in ("instability", "gait", "sit_stand", "wall_support", "pacing"))
        * 1.5,
    )
    labels = {
        "instability": "姿态不稳定",
        "gait": "步态变异较大",
        "sit_stand": "起身过程不稳",
        "pacing": "存在徘徊行为",
        "wall_support": "存在疑似扶墙行为",
    }
    reasons.extend(label for key, label in labels.items() if behavior.get(key, 0) >= 4)
    person_points = min(20.0, base + subjective)
    time_points = 0.0
    if behavior.get("night", 0) >= 4:
        time_points += 10
        reasons.append("夜间活动风险升高")
    recent_alert = (
        db.session.query(Alert)
        .filter_by(elder_id=elder.id)
        .filter(Alert.created_at >= now() - timedelta(days=7))
        .first()
    )
    if recent_alert is not None:
        time_points += 10
        reasons.append("近七日已有风险或跌倒告警")
    score = round(min(100.0, person_points + environment_points + behavior_points + time_points), 1)
    features = {
        "formulaVersion": current_app.config["RISK_FORMULA_VERSION"],
        "individual": round(person_points, 1),
        "environment": round(environment_points, 1),
        "behavior": round(behavior_points, 1),
        "time": round(time_points, 1),
        "suggestions": fixes,
        "behaviorRaw": behavior,
        "dataQuality": data_quality or {"sufficient": behavior is not None},
    }
    return score, reasons or ["当前未发现达到预警阈值的主要风险因素"], features


def persist_assessment(
    elder: Elder,
    scene: str,
    source: str,
    behavior: dict[str, float] | None = None,
    data_quality: dict | None = None,
) -> RiskAssessment:
    """保存一次版本化风险评估，并在达到高风险时创建解释性告警。"""
    score, reasons, features = score_risk(elder, scene, behavior, data_quality)
    assessment = RiskAssessment(
        elder_id=elder.id,
        scene=scene,
        source=source,
        score=score,
        level=risk_label(score),
        reasons=reasons,
        features=features,
    )
    db.session.add(assessment)
    db.session.flush()
    if assessment.level == "high":
        latest = (
            db.session.query(Alert)
            .filter_by(elder_id=elder.id, kind="high_risk")
            .filter(Alert.status != "closed")
            .order_by(desc(Alert.created_at))
            .first()
        )
        if latest is None or now() - latest.created_at > timedelta(hours=1):
            suggestions = features.get("suggestions") or ["先坐稳并联系家属"]
            reason_text = "；".join(reasons[:2])
            suggestion_text = "；".join(suggestions[:2])
            create_alert(
                elder,
                "high_risk",
                f"检测到高跌倒风险：{reason_text}。建议：{suggestion_text}。",
                assessment,
            )
    db.session.commit()
    return assessment


def create_alert(elder: Elder, kind: str, message: str, assessment: RiskAssessment | None = None) -> Alert:
    """创建告警及联系人邮件任务。"""
    deadline = now() + timedelta(seconds=current_app.config["ALERT_RESPONSE_SECONDS"]) if kind == "fall" else None
    alert = Alert(
        elder_id=elder.id,
        assessment_id=assessment.id if assessment else None,
        kind=kind,
        message=message,
        response_deadline=deadline,
    )
    db.session.add(alert)
    db.session.flush()
    title = "【安步守护】疑似跌倒告警" if kind == "fall" else "【安步守护】高跌倒风险提醒"
    for contact in db.session.query(Contact).filter_by(elder_id=elder.id).order_by(Contact.priority):
        db.session.add(
            Notification(
                alert_id=alert.id,
                recipient=contact.email,
                subject=title,
                body=f"{elder.name}：{message}\n{DISCLAIMER}",
            )
        )
    return alert


def _load_model():
    global _model
    if _model is None:
        path = current_app.config["MODEL_PATH"]
        if not path.is_file():
            return None
        from ultralytics import YOLO

        _model = YOLO(str(path))
    return _model


def fall_confidence(frame: np.ndarray) -> float:
    model = _load_model()
    if model is None:
        return 0.0
    result = model.predict(frame, imgsz=512, conf=0.15, iou=0.5, verbose=False)[0]
    return max((float(box.conf.item()) for box in result.boxes), default=0.0)


def analyze_live_frame(session: MonitorSession, frame: np.ndarray) -> dict:
    """分析实时画面，组合跌倒投票与多帧姿态行为信号。"""
    confidence = fall_confidence(frame)
    history = list(session.vote_history or [])[-5:] + [confidence >= 0.25]
    session.vote_history = history
    fall = len(history) == 6 and sum(history) >= 4
    elder = db.session.get(Elder, session.elder_id)
    if elder is None:
        raise ValueError("老人档案不存在")
    analyzer = _live_analyzers.setdefault(session.id, BehaviorAnalyzer(current_app.config["APP_TIMEZONE"]))
    sample = extract_pose_sample(frame, now())
    behavior_result = analyzer.update(sample) if sample else BehaviorResult(data_quality={"sufficient": False, "reason": "未识别到有效人体姿态"})
    persist_behavior_events(elder.id, session.scene, "live", behavior_result)
    assessment = persist_assessment(
        elder,
        session.scene,
        "live",
        behavior_result.scores,
        behavior_result.data_quality,
    )
    alert_id = None
    if fall:
        recent = (
            db.session.query(Alert)
            .filter_by(elder_id=elder.id, kind="fall")
            .filter(Alert.status != "closed")
            .order_by(desc(Alert.created_at))
            .first()
        )
        if recent is None or now() - recent.created_at > timedelta(minutes=3):
            alert = create_alert(
                elder,
                "fall",
                "连续多帧检测到疑似倒地，请立即确认老人状况。",
                assessment,
            )
            db.session.commit()
            alert_id = alert.id
    db.session.commit()
    return {
        "confidence": round(confidence, 3),
        "votes": sum(history),
        "fall": fall,
        "risk": serialize_assessment(assessment),
        "alertId": str(alert_id) if alert_id else None,
    }


def _get_pose_model():
    """按进程复用 MediaPipe 姿态模型，避免逐帧重复初始化。"""
    global _pose_model
    path = current_app.config["POSE_MODEL_PATH"]
    if not path.is_file():
        return None
    if _pose_model is None:
        import mediapipe as mp

        model_path = path
        try:
            str(path).encode("ascii")
        except UnicodeEncodeError:
            cache_dir = Path(tempfile.gettempdir()) / "anbu-models"
            cache_dir.mkdir(parents=True, exist_ok=True)
            model_path = cache_dir / "pose_landmarker_lite.task"
            if not model_path.is_file() or model_path.stat().st_size != path.stat().st_size:
                shutil.copy2(path, model_path)
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
        )
        _pose_model = mp.tasks.vision.PoseLandmarker.create_from_options(options)
    return _pose_model


def extract_pose_sample(frame: np.ndarray, timestamp) -> PoseSample | None:
    """从单帧图像提取规则引擎需要的归一化关键点。"""
    try:
        import mediapipe as mp

        pose = _get_pose_model()
        if pose is None:
            return None
        with _pose_lock:
            result = pose.detect(
                mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                )
            )
        if not result.pose_landmarks:
            return None
        lm = result.pose_landmarks[0]
        indexes = {
            "leftShoulder": 11,
            "rightShoulder": 12,
            "leftWrist": 15,
            "rightWrist": 16,
            "leftHip": 23,
            "rightHip": 24,
            "leftKnee": 25,
            "rightKnee": 26,
            "leftAnkle": 27,
            "rightAnkle": 28,
        }
        points = {
            name: (float(lm[index].x), float(lm[index].y), float(lm[index].visibility))
            for name, index in indexes.items()
            if float(lm[index].visibility) >= 0.35
        }
        return PoseSample(timestamp=timestamp, points=points)
    except Exception:
        current_app.logger.exception("姿态模型推理失败")
        return None


def persist_behavior_events(elder_id: int, scene: str, source: str, result: BehaviorResult) -> None:
    """保存规则引擎产生的派生事件，不保存原始人体关键点。"""
    for event in result.events:
        db.session.add(
            BehaviorEvent(
                elder_id=elder_id,
                scene=scene,
                event_type=event.event_type,
                severity=event.severity,
                confidence=event.confidence,
                score=event.score,
                evidence=event.evidence,
                source=source,
                started_at=event.started_at,
                ended_at=event.ended_at,
            )
        )


def stop_live_analyzer(session_id: int) -> None:
    """结束监测时释放会话级滚动行为状态。"""
    _live_analyzers.pop(session_id, None)


def process_pending_jobs(limit: int = 2) -> int:
    """处理本地上传视频，并在任意滚动窗口命中时创建一次跌倒告警。"""
    processed = 0
    for job in db.session.query(VideoJob).filter_by(status="pending").order_by(VideoJob.created_at).limit(limit):
        job.status = "running"
        db.session.commit()
        capture = None
        try:
            capture = cv2.VideoCapture(job.file_path)
            if not capture.isOpened():
                raise ValueError("视频无法解码或文件已损坏")
            fps = capture.get(cv2.CAP_PROP_FPS) or 25
            pose_stride = max(1, int(fps // 3))
            total_frames = max(0, int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
            job.total_frames = total_frames
            job.progress_frames = 0
            job.duration_seconds = round(total_frames / max(fps, 1), 3) if total_frames else None
            job.current_confidence = None
            job.frame_metrics = []
            db.session.commit()
            frame_no = 0
            votes: list[bool] = []
            frame_metrics: list[dict[str, float | bool]] = []
            behavior: dict[str, float] = {}
            data_quality: dict = {"sufficient": False, "reason": "未取得有效姿态"}
            analyzer = BehaviorAnalyzer(current_app.config["APP_TIMEZONE"])
            fall_detected = False
            decoded_frames = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                decoded_frames += 1
                confidence = fall_confidence(frame)
                is_fall_frame = confidence >= 0.25
                votes = votes[-5:] + [is_fall_frame]
                if len(votes) == 6 and sum(votes) >= 4:
                    fall_detected = True
                frame_metrics.append(
                    {
                        "time": round(frame_no / max(fps, 1), 3),
                        "confidence": round(float(confidence), 4),
                        "fall": is_fall_frame,
                    }
                )
                if frame_no % pose_stride == 0:
                    timestamp = job.created_at + timedelta(seconds=frame_no / max(fps, 1))
                    sample = extract_pose_sample(frame, timestamp)
                    result = analyzer.update(sample) if sample else BehaviorResult(data_quality=data_quality)
                    persist_behavior_events(job.elder_id, job.scene, "video", result)
                    data_quality = result.data_quality or data_quality
                    for key, value in result.scores.items():
                        behavior[key] = max(behavior.get(key, 0), value)
                if decoded_frames % 20 == 0:
                    job.progress_frames = decoded_frames
                    job.current_confidence = float(confidence)
                    job.frame_metrics = frame_metrics
                    db.session.commit()
                frame_no += 1
            if decoded_frames == 0:
                raise ValueError("视频中没有可读取的画面")
            elder = db.session.get(Elder, job.elder_id)
            if elder is None:
                raise ValueError("老人档案不存在")
            assessment = persist_assessment(elder, job.scene, "video", behavior, data_quality)
            if fall_detected:
                create_alert(elder, "fall", "上传视频中检测到疑似倒地，请立即确认。", assessment)
            job.progress_frames = decoded_frames
            job.current_confidence = frame_metrics[-1]["confidence"] if frame_metrics else None
            job.frame_metrics = frame_metrics
            job.status = "succeeded"
            job.completed_at = now()
            db.session.commit()
            processed += 1
        except Exception as error:
            db.session.rollback()
            job = db.session.get(VideoJob, job.id)
            if job:
                job.status = "failed"
                job.error_message = str(error)[:300]
                db.session.commit()
        finally:
            if capture is not None:
                capture.release()
    return processed


def process_pending_notifications(limit: int = 10) -> int:
    completed = 0
    for item in (
        db.session.query(Notification).filter_by(status="pending").order_by(Notification.created_at).limit(limit)
    ):
        item.attempts += 1
        try:
            if not current_app.config["SMTP_HOST"]:
                raise RuntimeError("未配置 SMTP_HOST")
            mail = EmailMessage()
            mail["Subject"] = item.subject
            mail["From"] = current_app.config["SMTP_FROM"]
            mail["To"] = item.recipient
            mail.set_content(item.body)
            with smtplib.SMTP(
                current_app.config["SMTP_HOST"],
                current_app.config["SMTP_PORT"],
                timeout=10,
            ) as client:
                if current_app.config["SMTP_USE_TLS"]:
                    client.starttls()
                if current_app.config["SMTP_USERNAME"]:
                    client.login(
                        current_app.config["SMTP_USERNAME"],
                        current_app.config["SMTP_PASSWORD"],
                    )
                client.send_message(mail)
            item.status = "sent"
            completed += 1
        except Exception as error:
            item.error_message = str(error)[:300]
            item.status = "pending" if item.attempts < 3 else "failed"
        db.session.commit()
    return completed


def expire_alerts() -> int:
    changed = 0
    for alert in db.session.query(Alert).filter_by(status="pending", kind="fall"):
        if alert.response_deadline and alert.response_deadline <= now():
            alert.status = "processing"
            db.session.add(
                Intervention(
                    alert_id=alert.id,
                    action="timeout_escalated",
                    note="老人未在倒计时内响应",
                )
            )
            elder = db.session.get(Elder, alert.elder_id)
            if elder:
                for contact in db.session.query(Contact).filter_by(elder_id=elder.id):
                    db.session.add(
                        Notification(
                            alert_id=alert.id,
                            recipient=contact.email,
                            subject="【安步守护】跌倒告警已升级",
                            body=f"{elder.name} 未在规定时间内响应，请立即联系或前往查看。",
                        )
                    )
            changed += 1
    if changed:
        db.session.commit()
    return changed


def serialize_assessment(item: RiskAssessment) -> dict:
    return {
        "id": str(item.id),
        "score": item.score,
        "level": item.level,
        "reasons": item.reasons,
        "features": item.features,
        "createdAt": item.created_at.isoformat(),
    }


def export_report(elder_id: int, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = db.session.query(RiskAssessment).filter_by(elder_id=elder_id).order_by(RiskAssessment.created_at).all()
    elder = db.session.get(Elder, elder_id)
    with target.open("w", encoding="utf-8") as handle:
        handle.write(
            f"# 安步守护风险报告\n\n- 老人：{elder.name if elder else elder_id}\n- 导出时间：{now().isoformat(timespec='seconds')}\n- 说明：{DISCLAIMER}\n\n"
        )
        handle.write(
            "## 风险评估记录\n\n| 时间 | 场景 | 来源 | 风险分 | 等级 | 风险原因 |\n| --- | --- | --- | ---: | --- | --- |\n"
        )
        for row in rows:
            handle.write(
                f"| {row.created_at.isoformat(timespec='minutes')} | {row.scene} | {row.source} | {row.score or '—'} | {row.level} | {'；'.join(row.reasons)} |\n"
            )
    return target
