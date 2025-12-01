from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings, sync_initial_settings
from app.connection import connect_to_db, disconnect_from_db
from app.initialization import initialize_database
from app.exceptions import setup_exception_handlers
from app.logger import Logger, setup_access_logging
from app.middleware import setup_middlewares
from app.routes import setup_routers
from app.scheduled_tasks import start_scheduler, stop_scheduler
from app.key_manager import get_key_manager_instance
from app.helpers import get_current_version

logger = Logger.setup_logger("application")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = PROJECT_ROOT / "app" / "static"
TEMPLATES_DIR = PROJECT_ROOT / "app" / "templates"

# 初始化模板引擎，并添加全局变量
templates = Jinja2Templates(directory="app/templates")

# --- Helper functions for lifespan ---
async def _setup_database_and_config(app_settings):
    """Initializes database, syncs settings, and initializes KeyManager."""
    await connect_to_db()
    await initialize_database()
    logger.info("Database initialized successfully")
    await sync_initial_settings()
    await get_key_manager_instance(app_settings.API_KEYS)
    logger.info("Database, config sync, and KeyManager initialized successfully")


async def _shutdown_database():
    """Disconnects from the database."""
    await disconnect_from_db()


def _start_scheduler():
    """Starts the background scheduler."""
    try:
        start_scheduler()
        logger.info("Scheduler started successfully.")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")


def _stop_scheduler():
    """Stops the background scheduler."""
    stop_scheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the application startup and shutdown events.

    Args:
        app: FastAPI应用实例
    """
    logger.info("Application starting up...")
    try:
        await _setup_database_and_config(settings)
        _start_scheduler()

    except Exception as e:
        logger.critical(
            f"Critical error during application startup: {str(e)}", exc_info=True
        )

    yield

    logger.info("Application shutting down...")
    _stop_scheduler()
    await _shutdown_database()


def create_app() -> FastAPI:
    """
    创建并配置FastAPI应用程序实例

    Returns:
        FastAPI: 配置好的FastAPI应用程序实例
    """

    # 创建FastAPI应用
    current_version = get_current_version()
    app = FastAPI(
        title="Gemini Balance API",
        description="Gemini API代理服务，支持负载均衡和密钥管理",
        version=current_version,
        lifespan=lifespan,
    )

    if not hasattr(app, "state"):
        from starlette.datastructures import State

        app.state = State()
    app.state.update_info = {
        "update_available": False,
        "latest_version": None,
        "error_message": "Initializing...",
        "current_version": current_version,
    }

    # 配置静态文件
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # 配置中间件
    setup_middlewares(app)

    # 配置异常处理器
    setup_exception_handlers(app)

    # 配置路由
    setup_routers(app)

    # 配置访问日志API密钥隐藏
    setup_access_logging()

    return app
