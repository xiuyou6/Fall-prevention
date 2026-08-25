"""三角色权限、事件闭环及导出报告测试。"""

from pathlib import Path

import numpy as np

from anbu.extensions import db
from anbu.models import Alert, Elder, ElderAccount, FamilyAssignment, RiskAssessment, User, VideoJob
from anbu.reports import build_events_csv, build_risk_pdf
from anbu.services import process_pending_jobs


def create_user(username: str, role: str, elder: Elder | None = None) -> User:
    user = User(username=username, display_name=username, role=role)
    user.set_password("password123")
    db.session.add(user)
    db.session.flush()
    if elder is not None:
        db.session.add(ElderAccount(user_id=user.id, elder_id=elder.id))
    return user


def login(client, username: str):
    password = "123456" if username == "admin" else "password123"
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_admin_creates_all_roles_and_protects_current_account(app, client):
    login(client, "admin")
    elder = Elder(name="老人", consent_granted=True)
    db.session.add(elder)
    db.session.commit()
    for role, elder_id in (("admin", None), ("family", None), ("elder", str(elder.id))):
        response = client.post(
            "/api/admin/users",
            json={"username": f"new-{role}", "displayName": role, "password": "password123", "role": role, "elderId": elder_id},
        )
        assert response.status_code == 201
        assert response.json["data"]["role"] == role
    current_id = client.get("/api/auth/me").json["data"]["user"]["userId"]
    assert client.patch(f"/api/admin/users/{current_id}", json={"isActive": False}).status_code == 409


def test_family_and_elder_permissions_are_scoped(app, client):
    first, second = Elder(name="已绑定", consent_granted=True), Elder(name="未绑定", consent_granted=True)
    db.session.add_all([first, second])
    db.session.flush()
    family = create_user("family-role", "family")
    create_user("elder-role", "elder", first)
    db.session.add(FamilyAssignment(user_id=family.id, elder_id=first.id))
    db.session.commit()

    login(client, "family-role")
    assert client.patch(f"/api/elders/{first.id}", json={"name": "越权"}).status_code == 403
    assert client.post(f"/api/elders/{first.id}/contacts", json={"name": "家属", "email": "a@example.com"}).status_code == 201
    assert client.get(f"/api/elders/{second.id}/contacts").status_code == 403

    client.post("/api/auth/logout")
    login(client, "elder-role")
    assert client.post(f"/api/elders/{first.id}/daily-checkins", json={"dizziness": 1}).status_code == 201
    assert client.post(f"/api/elders/{first.id}/contacts", json={"name": "越权", "email": "b@example.com"}).status_code == 403
    assert client.get(f"/api/elders/{second.id}/daily-checkins").status_code == 403


def test_alert_state_machine_rejects_skipped_transition(app, client):
    elder = Elder(name="测试", consent_granted=True)
    db.session.add(elder)
    db.session.flush()
    alert = Alert(elder_id=elder.id, kind="fall", status="pending", message="测试")
    db.session.add(alert)
    db.session.commit()
    login(client, "admin")
    assert client.patch(f"/api/alerts/{alert.id}", json={"action": "close"}).status_code == 409
    assert client.patch(f"/api/alerts/{alert.id}", json={"action": "confirm"}).status_code == 200
    assert client.patch(f"/api/alerts/{alert.id}", json={"action": "process"}).status_code == 200
    assert client.patch(f"/api/alerts/{alert.id}", json={"action": "close"}).status_code == 200


def test_uploaded_video_detects_fall_in_middle_window(app, monkeypatch, tmp_path):
    elder = Elder(name="测试", consent_granted=True)
    db.session.add(elder)
    db.session.flush()
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"fake")
    job = VideoJob(elder_id=elder.id, scene="客厅", file_path=str(video_path))
    db.session.add(job)
    db.session.commit()

    class Capture:
        def __init__(self, _path): self.index = 0
        def isOpened(self): return True
        def get(self, _property): return 3
        def read(self):
            if self.index >= 12: return False, None
            self.index += 1
            return True, np.zeros((8, 8, 3), dtype=np.uint8)
        def release(self): return None

    values = iter([0.9, 0.9, 0.9, 0.9, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    monkeypatch.setattr("anbu.services.cv2.VideoCapture", Capture)
    monkeypatch.setattr("anbu.services.fall_confidence", lambda _frame: next(values))
    monkeypatch.setattr("anbu.services.extract_pose_sample", lambda _frame, _timestamp: None)
    assert process_pending_jobs() == 1
    assert db.session.query(Alert).filter_by(elder_id=elder.id, kind="fall").count() == 1
    completed_job = db.session.get(VideoJob, job.id)
    assert completed_job is not None
    assert len(completed_job.frame_metrics) == 12
    assert completed_job.frame_metrics[4]["time"] > completed_job.frame_metrics[3]["time"]
    assert completed_job.current_confidence == 0.0


def test_video_preview_requires_authorized_family_access(app, client, tmp_path):
    elder = Elder(name="已授权", consent_granted=True)
    db.session.add(elder)
    db.session.flush()
    family = create_user("preview-family", "family")
    create_user("preview-outsider", "family")
    db.session.add(FamilyAssignment(user_id=family.id, elder_id=elder.id))
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    app.config["UPLOAD_ROOT"] = upload_root
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_bytes(b"local-video")
    job = VideoJob(elder_id=elder.id, scene="客厅", file_path=str(preview_file))
    db.session.add(job)
    db.session.commit()

    login(client, "preview-family")
    assert client.get(f"/api/video-jobs/{job.id}/preview").status_code == 404

    job.file_path = str(upload_root / "preview.mp4")
    Path(job.file_path).write_bytes(b"local-video")
    db.session.commit()
    response = client.get(f"/api/video-jobs/{job.id}/preview")
    assert response.status_code == 200
    assert response.mimetype == "video/mp4"
    assert response.data == b"local-video"
    job.frame_metrics = [{"time": 0.0, "confidence": 0.42, "fall": True}]
    job.current_confidence = 0.42
    db.session.commit()
    details = client.get(f"/api/video-jobs/{job.id}")
    assert details.status_code == 200
    assert details.json["data"]["frameMetrics"] == [{"time": 0.0, "confidence": 0.42, "fall": True}]

    client.post("/api/auth/logout")
    login(client, "preview-outsider")
    assert client.get(f"/api/video-jobs/{job.id}/preview").status_code == 403
    assert client.get("/api/video-jobs/99999/preview").status_code == 404


def test_pdf_and_csv_reports_include_auditable_records(app, tmp_path):
    elder = Elder(name="报告老人", consent_granted=True)
    db.session.add(elder)
    db.session.flush()
    db.session.add(RiskAssessment(elder_id=elder.id, scene="客厅", source="test", score=72, level="high", reasons=["测试风险"], features={"individual": 20, "behavior": 27, "environment": 25, "time": 0}))
    db.session.commit()
    pdf = build_risk_pdf(elder.id, tmp_path / "risk.pdf")
    csv_file = build_events_csv(elder.id, tmp_path / "events.csv")
    assert pdf.read_bytes().startswith(b"%PDF")
    assert csv_file.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "risk" in csv_file.read_text(encoding="utf-8-sig")
