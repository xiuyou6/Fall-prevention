"""Playwright 三角色验收使用的隔离 Flask 服务。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anbu import create_app
from anbu.extensions import db
from anbu.models import Elder, ElderAccount, FamilyAssignment, User
from anbu.services import bootstrap_database

app = create_app(
    {
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "TESTING": True,
        "RUN_BACKGROUND_WORKER": False,
    }
)

with app.app_context():
    bootstrap_database()
    elder = Elder(name="端到端测试老人", birth_year=1945, consent_granted=True)
    family = User(username="e2e-family", display_name="测试家属", role="family")
    family.set_password("password123")
    senior = User(username="e2e-elder", display_name="测试老人", role="elder")
    senior.set_password("password123")
    db.session.add_all([elder, family, senior])
    db.session.flush()
    db.session.add_all(
        [
            FamilyAssignment(user_id=family.id, elder_id=elder.id),
            ElderAccount(user_id=senior.id, elder_id=elder.id),
        ]
    )
    db.session.commit()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False)
