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
    一个基于可配置时间窗口和请求后校正的Token速率限制器。
    它采用“立即拒绝”策略。
    """

    def __init__(self):
        self._limiters: Dict[str, Dict] = {}
        self._parse_config()

    def _parse_config(self):
        """从设置中解析Token限制配置。"""
        try:
            limits_config_str = settings.MODEL_TPM_LIMITS
            if isinstance(limits_config_str, dict):
                limits_config = limits_config_str
            else:
                limits_config = json.loads(limits_config_str or "{}")

            if not isinstance(limits_config, dict):
                logger.warning("MODEL_TPM_LIMITS 不是一个有效的字典。将不应用Token限制。")
                return

            for model, config in limits_config.items():
                limit = None
                window_seconds = 60  # 默认为1分钟

                if isinstance(config, int):
                    # 向后兼容：如果值是整数，则视为limit，窗口为60秒
                    limit = config
                elif isinstance(config, dict):
                    limit = config.get("limit")
                    window_seconds = config.get("window_seconds", 60)
                else:
                    logger.warning(
                        f"模型 '{model}' 的配置格式无效: {config}。跳过。"
                    )
                    continue

                if not isinstance(limit, int) or limit <= 0:
                    logger.warning(
                        f"模型 '{model}' 的 'limit' 无效: {limit}。必须是正整数。跳过。"
                    )
                    continue

                if not isinstance(window_seconds, int) or window_seconds <= 0:
                    logger.warning(
                        f"模型 '{model}' 的 'window_seconds' 无效: {window_seconds}。必须是正整数。跳过。"
                    )
                    continue

                self._limiters[model] = {
                    "lock": asyncio.Lock(),
                    "limit": limit,
                    "window_seconds": window_seconds,
                    "window_start_time": 0.0,
                    "token_count": 0,
                }
                logger.info(
                    f"为模型 '{model}' 启用Token速率限制: {limit} Tokens / {window_seconds}s"
                )
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"无法解析 MODEL_TPM_LIMITS。错误: {e}。将不应用Token限制。")
            self._limiters = {}

    async def reserve_tokens(self, model_name: str, estimated_tokens: int):
        """
        检查并预留估算的token数。如果超出限制，则抛出 RateLimitExceededError。
        """
        limiter = self._limiters.get(model_name)
        if not limiter:
            return

        limit = limiter["limit"]
        window_seconds = limiter["window_seconds"]

        if estimated_tokens > limit:
            raise RateLimitExceededError(
                f"请求的预估token数 ({estimated_tokens}) 超过了模型在 {window_seconds}s 窗口内的Token限制 ({limit})。"
            )

        async with limiter["lock"]:
            now = time.monotonic()
            window_start = limiter["window_start_time"]

            if now > window_start + window_seconds:
                logger.debug(f"模型 '{model_name}' 的Token限制窗口已重置。")
                limiter["window_start_time"] = now
                limiter["token_count"] = 0

            if limiter["token_count"] + estimated_tokens > limit:
                time_to_wait = (window_start + window_seconds) - now
                raise RateLimitExceededError(
                    f"模型 '{model_name}' 的Token速率限制已超出。"
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


class IndividualKeyRateLimiter:
    """
    为池中的每个API密钥在特定模型上应用独立的速率限制。
    当某个密钥在某个模型上达到限制后，它会暂时从该模型的轮询中移除，
    直到限制窗口过去后自动恢复。
    """

    def __init__(self):
        self._limiters: Dict[str, Dict[str, int]] = {}  # {model: {rpm: x, tpm: y, rpd: z}}
        self._usage: Dict[str, Dict[str, Dict[str, Any]]] = {}  # {model: {api_key: {usage_data}}}
        self._lock = asyncio.Lock()
        self._parse_config()

    def _parse_config(self):
        """从设置中解析每个模型下单个Key的速率限制配置。"""
        try:
            limits_config_str = settings.MODEL_KEY_LIMITS
            limits_config = json.loads(limits_config_str or "{}")

            if not isinstance(limits_config, dict):
                logger.warning("MODEL_KEY_LIMITS 不是一个有效的字典。将不应用密钥速率限制。")
                return

            for model, config in limits_config.items():
                if not isinstance(config, dict):
                    logger.warning(f"模型 '{model}' 的密钥限制配置格式无效，应为字典。跳过。")
                    continue
                
                validated_limits = {}
                for limit_type in ["rpm", "tpm", "rpd"]:
                    limit_value = config.get(limit_type)
                    if limit_value is not None:
                        if isinstance(limit_value, int) and limit_value > 0:
                            validated_limits[limit_type] = limit_value
                        else:
                            logger.warning(f"模型 '{model}' 的 '{limit_type}' 值无效: {limit_value}。必须是正整数。")
                
                if validated_limits:
                    self._limiters[model] = validated_limits
                    logger.info(f"为模型 '{model}' 启用独立密钥速率限制: {validated_limits}")

        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"无法解析 MODEL_KEY_LIMITS。错误: {e}。将不应用密钥速率限制。")
            self._limiters = {}

    async def check_and_reserve(self, model_name: str, api_key: str, tokens_to_use: int = 0):
        """
        检查指定密钥在指定模型上是否超出限制。如果未超出，则预留资源。
        如果超出限制，则抛出 RateLimitExceededError。
        (逻辑将在下一步实现)
        """
        pass

    async def release(self, model_name: str, api_key: str, tokens_to_use: int = 0):
        """
        当API调用失败时，释放之前预留的资源。
        (逻辑将在下一步实现)
        """
        pass

    async def update_token_usage(self, model_name: str, api_key: str, reserved_tokens: int, actual_tokens: int):
        """
        根据实际使用的Token数校正TPM计数。
        (逻辑将在下一步实现)
        """
        pass


# 单个密钥速率限制器的单例实例
key_rate_limiter = IndividualKeyRateLimiter()