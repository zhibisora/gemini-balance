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
    一个基于滑动时间窗口的TPM（每分钟Token数）速率限制器。
    它采用“立即拒绝”策略，以解决固定窗口的边界突发问题。
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
                    "window_start_time": time.monotonic(),
                    "previous_window_count": 0,
                    "current_window_count": 0,
                }
                logger.info(
                    f"为模型 '{model}' 启用滑动窗口TPM速率限制: {limit} Tokens/分钟"
                )
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"无法解析 MODEL_TPM_LIMITS。错误: {e}。将不应用TPM限制。")
            self._limiters = {}

    async def check_and_update(self, model_name: str, estimated_tokens: int):
        """
        检查请求是否超过滑动窗口的TPM限制。如果未超过，则更新计数器。
        如果超过，则抛出 RateLimitExceededError。
        """
        limiter = self._limiters.get(model_name)
        if not limiter:
            # 此模型没有配置限制，直接允许
            return

        limit = limiter["limit"]
        if estimated_tokens > limit:
            raise RateLimitExceededError(
                f"请求的预估token数 ({estimated_tokens}) 超过了模型的TPM限制 ({limit})。"
            )

        async with limiter["lock"]:
            now = time.monotonic()
            window_start = limiter["window_start_time"]

            # --- 滑动窗口核心逻辑 ---
            # 1. 检查并推进窗口
            if now >= window_start + self._window_size:
                windows_passed = int((now - window_start) / self._window_size)
                
                if windows_passed == 1:
                    # 正常推进一个窗口
                    limiter["previous_window_count"] = limiter["current_window_count"]
                    limiter["current_window_count"] = 0
                else:
                    # 如果跳过了多个窗口（例如，长时间无请求），则两个窗口都清零
                    limiter["previous_window_count"] = 0
                    limiter["current_window_count"] = 0
                
                # 更新窗口的起始时间
                limiter["window_start_time"] += windows_passed * self._window_size


            # 2. 计算当前滑动窗口内的预估Token总数
            # 计算上一个窗口的权重（即上一个窗口还剩多少比例在当前的滑动时间内）
            time_in_current_window = now - limiter["window_start_time"]
            weight = (self._window_size - time_in_current_window) / self._window_size
            
            previous_window_contribution = limiter["previous_window_count"] * weight
            
            current_sliding_count = previous_window_contribution + limiter["current_window_count"]

            # 3. 检查是否会超出限制
            if current_sliding_count + estimated_tokens > limit:
                raise RateLimitExceededError(
                    f"模型 '{model_name}' 的TPM速率限制已超出。"
                    f"当前估算值: {int(current_sliding_count)}/{limit} Tokens/分钟。"
                )

            # 4. 更新当前窗口的计数器
            limiter["current_window_count"] += estimated_tokens
            logger.debug(
                f"模型 '{model_name}' 的TPM计数更新: "
                f"当前窗口计数={limiter['current_window_count']}, "
                f"滑动窗口估算值={int(current_sliding_count + estimated_tokens)}/{limit}"
            )


# 速率限制器的单例实例
rate_limiter = ModelRateLimiter()