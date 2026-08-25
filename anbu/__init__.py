"""Flask application factory."""

import threading
from pathlib import Path
from typing import Any

from flask import Flask, request

from .config import Config
from .extensions import csrf, db


def create_app(config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    if config:
        app.config.update(config)
    if not app.config.get("TESTING") and app.config["APP_ENV"] == "production":
        if app.config["SECRET_KEY"] == "development-only-change-me":
            raise RuntimeError("生产环境必须配置安全的 SECRET_KEY")
        if app.config["BOOTSTRAP_ADMIN_PASSWORD"] == "123456" or len(app.config["BOOTSTRAP_ADMIN_PASSWORD"]) < 8:
            raise RuntimeError("生产环境必须配置至少 8 位的 BOOTSTRAP_ADMIN_PASSWORD")
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config["UPLOAD_ROOT"].mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    csrf.init_app(app)

    from .routes import web

    app.register_blueprint(web)

    @app.after_request
    def add_api_cors_headers(response):
        """Allow only configured local SPA origins to use cookie-authenticated APIs."""
        origin = request.headers.get("Origin")
        if request.path.startswith("/api/") and origin in app.config["CORS_ORIGINS"]:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-CSRFToken"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
            response.headers["Vary"] = "Origin"
        return response

    # 单机部署时由 Web 进程负责本地视频、邮件和超时告警任务，避免额外启动 worker.py。
    if not app.config.get("TESTING"):
        with app.app_context():
            from .services import bootstrap_database

            bootstrap_database()
        _start_background_worker(app)

    @app.cli.command("init-db")
    def init_db() -> None:
        from .services import bootstrap_database

        bootstrap_database()
        print("数据库初始化完成")

    return app


def _start_background_worker(app: Flask) -> None:
    """Attach exactly one daemon worker to this Flask process."""
    if not app.config["RUN_BACKGROUND_WORKER"] or app.extensions.get("anbu_background_worker"):
        return

    stop_event = threading.Event()

    def run() -> None:
        from .services import expire_alerts, process_pending_jobs, process_pending_notifications

        with app.app_context():
            while not stop_event.is_set():
                try:
                    process_pending_jobs(limit=2)
                    process_pending_notifications(limit=10)
                    expire_alerts()
                except Exception:
                    db.session.rollback()
                    app.logger.exception("后台任务循环失败，将在下个周期重试")
                stop_event.wait(app.config["WORKER_POLL_SECONDS"])

    thread = threading.Thread(target=run, name="anbu-background-worker", daemon=True)
    app.extensions["anbu_background_worker"] = {"thread": thread, "stop_event": stop_event}
    thread.start()
