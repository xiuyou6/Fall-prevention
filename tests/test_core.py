from anbu import create_app
from anbu.extensions import db
from datetime import timedelta

from anbu.models import Alert, DailyCheckin, Elder, ElderAccount, EnvironmentCheck, FamilyAssignment, User, now
from anbu.services import bootstrap_database, expire_alerts, score_risk


def make_app():
    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "TESTING": True,
            "RUN_BACKGROUND_WORKER": False,
        }
    )
    app.app_context().push()
    bootstrap_database()
    return app


def test_risk_score_combines_all_input_domains():
    make_app()
    elder = Elder(
        name="测试",
        birth_year=1935,
        prior_falls=True,
        mobility_level="assisted",
        assistive_device="助行器",
        consent_granted=True,
    )
    db.session.add(elder)
    db.session.flush()
    db.session.add(
        EnvironmentCheck(
            elder_id=elder.id,
            scene="卫生间",
            wet_floor=True,
            dim_light=True,
            missing_handrail=True,
        )
    )
    db.session.add(
        DailyCheckin(
            elder_id=elder.id,
            dizziness=5,
            fatigue=5,
            sleep_quality=1,
            pain=4,
            medication_changed=True,
        )
    )
    db.session.commit()
    score, reasons, features = score_risk(elder, "卫生间", {"instability": 12, "gait": 8})
    assert score >= 70
    assert "有既往跌倒史" in reasons
    assert features["environment"] > 0


def test_api_login_and_consent_guard():
    app = make_app()
    client = app.test_client()
    assert client.post("/api/auth/login", json={"username": "admin", "password": "123456"}).status_code == 200
    elder = Elder(name="未授权老人", consent_granted=False)
    db.session.add(elder)
    db.session.commit()
    assert client.post(f"/api/elders/{elder.id}/monitor-sessions", json={"scene": "客厅"}).status_code == 403


def test_expired_alert_uses_sqlite_compatible_times():
    make_app()
    elder = Elder(name="测试", consent_granted=True)
    db.session.add(elder)
    db.session.flush()
    db.session.add(
        Alert(
            elder_id=elder.id,
            kind="fall",
            status="pending",
            message="测试告警",
            response_deadline=now() - timedelta(seconds=1),
        )
    )
    db.session.commit()
    assert expire_alerts() == 1
    assert db.session.query(Alert).one().status == "processing"


def test_elder_role_cannot_open_management_api():
    app = make_app()
    elder = Elder(name="老人", consent_granted=True)
    db.session.add(elder)
    db.session.flush()
    user = User(username="elder-1", display_name="老人", role="elder")
    user.set_password("abcdef")
    db.session.add(user)
    db.session.flush()
    db.session.add(ElderAccount(user_id=user.id, elder_id=elder.id))
    db.session.commit()
    client = app.test_client()
    assert client.post("/api/auth/login", json={"username": "elder-1", "password": "abcdef"}).status_code == 200
    assert client.get("/api/elders").status_code == 403


def test_family_can_only_open_assigned_elder_api_data():
    app = make_app()
    first, second = Elder(name="已授权"), Elder(name="未授权")
    db.session.add_all([first, second])
    db.session.flush()
    family = User(username="family", display_name="家属", role="family")
    family.set_password("abcdef")
    db.session.add(family)
    db.session.flush()
    db.session.add(FamilyAssignment(user_id=family.id, elder_id=first.id))
    db.session.commit()
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "family", "password": "abcdef"})
    assert client.get(f"/api/elders/{first.id}/contacts").status_code == 200
    assert client.get(f"/api/elders/{second.id}/contacts").status_code == 403
