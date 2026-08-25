"""Runtime configuration loaded from environment variables."""

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _path(name: str, default: str) -> Path:
    return Path(os.getenv(name, str(ROOT / default))).resolve()


class Config:
    APP_ENV = os.getenv("APP_ENV", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///anbu.sqlite3")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_ROOT = _path("UPLOAD_ROOT", "uploads")
    MODEL_PATH = _path("MODEL_PATH", "models/fall_detection_yolo26s_best.pt")
    POSE_MODEL_PATH = _path("POSE_MODEL_PATH", "models/pose_landmarker_lite.task")
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024
    ALERT_RESPONSE_SECONDS = int(os.getenv("ALERT_RESPONSE_SECONDS", "60"))
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    WTF_CSRF_TIME_LIMIT = 3600
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    RUN_BACKGROUND_WORKER = os.getenv("RUN_BACKGROUND_WORKER", "true").lower() == "true"
    WORKER_POLL_SECONDS = max(1, int(os.getenv("WORKER_POLL_SECONDS", "2")))
    BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "123456")
    CORS_ORIGINS = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        if origin.strip()
    )
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
    ALERT_POLL_SECONDS = max(3, int(os.getenv("ALERT_POLL_SECONDS", "10")))
    MAX_VIDEO_BYTES = min(MAX_CONTENT_LENGTH, int(os.getenv("MAX_VIDEO_BYTES", str(500 * 1024 * 1024))))
    RISK_FORMULA_VERSION = "v2"
