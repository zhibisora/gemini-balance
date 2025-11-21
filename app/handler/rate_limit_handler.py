import asyncio
import json
from contextlib import asynccontextmanager
from typing import Dict

from app.config.config import settings
from app.log.logger import get_main_logger

logger = get_main_logger()


class ModelRateLimiter:
    """一个基于并发和延迟对不同模型进行速率限制的限制器。"""

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

                concurrency = config.get("concurrency", 1)
                delay = config.get("delay", 0)

                if not isinstance(concurrency, int) or concurrency <= 0:
                    logger.warning(
                        f"模型 '{model}' 的并发数无效: {concurrency}。必须是正整数。默认为1。"
                    )
                    concurrency = 1

                if not isinstance(delay, (int, float)) or delay < 0:
                    logger.warning(
                        f"模型 '{model}' 的延迟无效: {delay}。必须是非负数。默认为0。"
                    )
                    delay = 0

                self._limiters[model] = {
                    "semaphore": asyncio.Semaphore(concurrency),
                    "delay": delay,
                }
                logger.info(
                    f"为模型 '{model}' 启用速率限制: 并发数={concurrency}, 延迟={delay}s"
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

        semaphore = limiter["semaphore"]
        delay = limiter["delay"]

        logger.debug(f"正在为模型 '{model_name}' 获取信号量...")
        await semaphore.acquire()
        logger.debug(f"已为模型 '{model_name}' 获取信号量。")
        try:
            yield
        finally:
            if delay > 0:
                logger.debug(f"正在为模型 '{model_name}' 等待 {delay}s 延迟...")
                await asyncio.sleep(delay)
            semaphore.release()
            logger.debug(f"已为模型 '{model_name}' 释放信号量。")


# 速率限制器的单例实例
rate_limiter = ModelRateLimiter()