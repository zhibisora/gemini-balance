import asyncio
import json
import time
from typing import Dict

from app.config.config import settings
from app.exception.exceptions import RateLimitExceededError
from app.log.logger import get_main_logger

logger = get_main_logger()


class ModelRateLimiter:
    """
    一个基于固定时间窗口和请求后校正的TPM（每分钟Token数）速率限制器。
    它采用“立即拒绝”策略。
    """

    def __init__(self, window_size_seconds: int = 60):
        self._limiters: Dict[str, Dict] = {}
        self._window_size = window_size_seconds
        self._parse_config()

    def _parse_config(self):
        """从设置中解析TPM限制配置。"""
        try:
            limits_config_str = settings.MODEL_TPM_LIMITS
            if isinstance(limits_config_str, dict):
                limits_config = limits_config_str
            else:
                limits_config = json.loads(limits_config_str or "{}")

            if not isinstance(limits_config, dict):
                logger.warning("MODEL_TPM_LIMITS 不是一个有效的字典。将不应用TPM限制。")
                return

            for model, limit in limits_config.items():
                if not isinstance(limit, int) or limit <= 0:
                    logger.warning(
                        f"模型 '{model}' 的TPM限制无效: {limit}。必须是正整数。跳过。"
                    )
                    continue

                self._limiters[model] = {
                    "lock": asyncio.Lock(),
                    "limit": limit,
                    "window_start_time": 0.0,
                    "token_count": 0,
                }
                logger.info(f"为模型 '{model}' 启用TPM速率限制: {limit} Tokens/分钟")
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"无法解析 MODEL_TPM_LIMITS。错误: {e}。将不应用TPM限制。")
            self._limiters = {}

    async def reserve_tokens(self, model_name: str, estimated_tokens: int):
        """
        检查并预留估算的token数。如果超出限制，则抛出 RateLimitExceededError。
        """
        limiter = self._limiters.get(model_name)
        if not limiter:
            return

        limit = limiter["limit"]
        if estimated_tokens > limit:
            raise RateLimitExceededError(
                f"请求的预估token数 ({estimated_tokens}) 超过了模型的TPM限制 ({limit})。"
            )

        async with limiter["lock"]:
            now = time.monotonic()
            window_start = limiter["window_start_time"]

            if now > window_start + self._window_size:
                logger.debug(f"模型 '{model_name}' 的TPM窗口已重置。")
                limiter["window_start_time"] = now
                limiter["token_count"] = 0

            if limiter["token_count"] + estimated_tokens > limit:
                time_to_wait = (window_start + self._window_size) - now
                raise RateLimitExceededError(
                    f"模型 '{model_name}' 的TPM速率限制已超出。"
                    f"请在 {time_to_wait:.2f} 秒后重试。"
                )

            limiter["token_count"] += estimated_tokens
            logger.debug(
                f"为模型 '{model_name}' 预留了 {estimated_tokens} tokens。 "
                f"当前窗口计数: {limiter['token_count']}/{limit}"
            )

    async def adjust_token_count(
        self, model_name: str, estimated_tokens: int, actual_tokens: int
    ):
        """
        根据实际消耗的token数校正计数器。
        如果API调用失败，actual_tokens应为0，以回滚预留。
        """
        limiter = self._limiters.get(model_name)
        if not limiter:
            return

        delta = actual_tokens - estimated_tokens
        if delta == 0:
            return

        async with limiter["lock"]:
            # 确保计数器不会变为负数
            limiter["token_count"] = max(0, limiter["token_count"] + delta)
            logger.debug(
                f"TPM计数已为模型 '{model_name}' 校正 {delta} tokens (估算: {estimated_tokens}, 实际: {actual_tokens})。 "
                f"新计数: {limiter['token_count']}/{limiter['limit']}"
            )


# 速率限制器的单例实例
rate_limiter = ModelRateLimiter()