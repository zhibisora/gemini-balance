"""
异常处理模块，定义应用程序中使用的自定义异常和异常处理器
"""
from fastapi import HTTPException
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logger import Logger

logger = Logger.setup_logger("exceptions")


class APIError(Exception):
    """API错误基类"""

    def __init__(self, status_code: int, detail: str, error_code: str = None):
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code or "api_error"
        super().__init__(self.detail)


class RateLimitExceededError(HTTPException):
    """当TPM速率限制被触发时抛出此异常。"""

    def __init__(self, message: str):
        super().__init__(status_code=429, detail=message)


class RequestTooLargeError(RateLimitExceededError):
    """当单次请求的Token数超过限制时抛出。"""

    def __init__(self, message: str):
        super().__init__(message=message)


def setup_exception_handlers(app: FastAPI) -> None:
    """
    设置应用程序的异常处理器

    Args:
        app: FastAPI应用程序实例
    """
    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        """处理API错误"""
        logger.error(f"API Error: {exc.detail} (Code: {exc.error_code})")
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.error_code, "message": exc.detail}},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """处理HTTP异常"""
        logger.error(f"HTTP Exception: {exc.detail} (Status: {exc.status_code})")
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "http_error", "message": exc.detail}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        """处理请求验证错误"""
        error_details = []
        for error in exc.errors():
            error_details.append(
                {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
            )

        logger.error(f"Validation Error: {error_details}")
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": error_details,
                }
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """处理通用异常"""
        logger.exception(f"Unhandled Exception: {str(exc)}")
        return JSONResponse(
            status_code=500,
            content=str(exc),
        )
