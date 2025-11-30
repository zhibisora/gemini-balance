
from functools import wraps
from typing import Callable, TypeVar

from app.config.config import settings
from app.log.logger import get_retry_logger
from app.utils.helpers import redact_key_for_logging

T = TypeVar("T")
logger = get_retry_logger()


class RetryHandler:
    """重试处理装饰器"""

    def __init__(self, key_arg: str = "api_key"):
        self.key_arg = key_arg

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(settings.MAX_RETRIES):
                retries = attempt + 1
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    # 检查是否为可重试的503错误
                    status_code = None
                    if hasattr(e, "args") and len(e.args) > 0 and isinstance(e.args[0], int):
                        status_code = e.args[0]

                    if status_code != 503:
                        logger.error(f"Non-retryable error encountered (status: {status_code}): {str(e)}. Failing fast.")
                        raise e  # 如果不是503错误，立即将错误向下传递

                    # --- 503错误，执行重试逻辑 ---
                    last_exception = e
                    logger.warning(
                        f"API call failed with 503 error. Attempt {retries} of {settings.MAX_RETRIES}. Retrying..."
                    )

                    # 从函数参数中获取 key_manager
                    key_manager = kwargs.get("key_manager")
                    if key_manager:
                        old_key = kwargs.get(self.key_arg)
                        new_key = await key_manager.handle_api_failure(old_key, retries)
                        if new_key:
                            kwargs[self.key_arg] = new_key
                            logger.info(f"Switched to new API key: {redact_key_for_logging(new_key)}")
                        else:
                            logger.error(f"No valid API key available after {retries} retries.")
                            break

            logger.error(
                f"All retry attempts for 503 error failed, raising final exception: {str(last_exception)}"
            )
            raise last_exception

        return wrapper
