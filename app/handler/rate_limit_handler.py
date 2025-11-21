import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import Dict

from app.config.config import settings
from app.log.logger import get_main_logger

logger = get_main_logger()


class ModelRateLimiter:
    """一个基于请求间隔对不同模型进行速率限制的限制器。"""

    def __init__(self):
        self._limiters: Dict[str, Dict] = {}
        self._parse_config()

    def _parse_config(self):
        """从设置中解析速率限制配置。"""
        try:
            # 配置可以是一个字符串（来自.env）或一个字典（来自数据库/json配置）
            limits_config_str = settings.MODEL_RATE_LIMITS
            if isinstance(limits_config_str, dict):
                limits_config = limits_config_str
            else:
                limits_config = json.loads(limits_config_str or "{}")

            if not isinstance(limits_config, dict):
                logger.warning(
                    "MODEL_RATE_LIMITS 不是一个有效的字典。将不应用任何速率限制。"
                )
                return

            for model, config in limits_config.items():
                if not isinstance(config, dict):
                    logger.warning(
                        f"模型 '{model}' 的配置不是一个字典。跳过。"
                    )
                    continue

                interval = config.get("interval", 0)

                if not isinstance(interval, (int, float)) or interval < 0:
                    logger.warning(
                        f"模型 '{model}' 的间隔无效: {interval}。必须是非负数。默认为0。"
                    )
                    interval = 0

                if interval > 0:
                    self._limiters[model] = {
                        "lock": asyncio.Lock(),
                        "interval": interval,
                        "next_allowed_time": 0.0,
                    }
                    logger.info(
                        f"为模型 '{model}' 启用速率限制: 最小间隔={interval}s"
                    )
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(
                f"无法解析 MODEL_RATE_LIMITS。错误: {e}。将不应用任何速率限制。"
            )
            self._limiters = {}

    @asynccontextmanager
    async def limit(self, model_name: str):
        """一个异步上下文管理器，用于为给定模型应用速率限制。"""
        limiter = self._limiters.get(model_name)
        if not limiter:
            # 如果没有为此模型配置限制器，则直接执行并返回。
            yield
            return

        lock = limiter["lock"]
        interval = limiter["interval"]

        async with lock:
            now = time.monotonic()
            next_time = limiter.get("next_allowed_time", 0.0)

            wait_for = next_time - now
            if wait_for > 0:
                logger.debug(
                    f"速率限制模型 '{model_name}', 等待 {wait_for:.4f}s."
                )
                await asyncio.sleep(wait_for)

            # 更新此模型的下一次允许时间
            limiter["next_allowed_time"] = time.monotonic() + interval

        try:
            yield
        finally:
            # 在这种模式下，退出时无需执行任何操作
            pass


# 速率限制器的单例实例
rate_limiter = ModelRateLimiter()