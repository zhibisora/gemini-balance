import time
from typing import Any, AsyncGenerator, Dict, Union

from fastapi import HTTPException
from app.config.config import settings
from app.database.services import (
    add_error_log,
    add_request_log,
)
from app.domain.openai_models import ChatRequest, ImageGenerationRequest
from app.exception.exceptions import RateLimitExceededError
from app.handler.rate_limit_handler import key_rate_limiter, rate_limiter
from app.log.logger import get_openai_compatible_logger
from app.service.client.api_client import OpenaiApiClient
from app.service.key.key_manager import KeyManager
from app.utils.helpers import estimate_payload_tokens, redact_key_for_logging

logger = get_openai_compatible_logger()


class OpenAICompatiableService:

    def __init__(self, base_url: str, key_manager: KeyManager = None):
        self.key_manager = key_manager
        self.base_url = base_url
        self.api_client = OpenaiApiClient(base_url, settings.TIME_OUT)

    async def get_models(self, api_key: str) -> Dict[str, Any]:
        return await self.api_client.get_models(api_key)

    async def create_chat_completion(
        self,
        request: ChatRequest,
        api_key: str,
    ) -> Union[Dict[str, Any], AsyncGenerator[str, None]]:
        """创建聊天完成"""
        request_dict = request.model_dump()
        # 移除值为null的
        request_dict = {k: v for k, v in request_dict.items() if v is not None}
        if "top_k" in request_dict:
            del request_dict["top_k"]  # 删除top_k参数，目前不支持该参数

        if request.stream:
            return self._handle_stream_completion(request.model, request_dict, api_key)
        return await self._handle_normal_completion(
            request.model, request_dict, api_key
        )

    async def generate_images(
        self,
        request: ImageGenerationRequest,
    ) -> Dict[str, Any]:
        """生成图片"""
        request_dict = request.model_dump()
        # 移除值为null的
        request_dict = {k: v for k, v in request_dict.items() if v is not None}
        api_key = settings.PAID_KEY
        async with rate_limiter.limit(request.model):
            return await self.api_client.generate_images(request_dict, api_key)

    async def create_embeddings(
        self,
        input_text: str,
        model: str,
        api_key: str,
    ) -> Dict[str, Any]:
        """创建嵌入"""
        async with rate_limiter.limit(model):
            return await self.api_client.create_embeddings(input_text, model, api_key)

    async def _handle_normal_completion(
        self, model: str, request: dict, api_key: str
    ) -> Dict[str, Any]:
        """处理普通聊天完成"""
        estimated_tokens = estimate_payload_tokens(request)

        # --- 查找可用密钥 ---
        if not self.key_manager:
            raise HTTPException(status_code=500, detail="KeyManager is not initialized.")
        number_of_keys = len(self.key_manager.api_keys)
        if number_of_keys == 0:
            raise HTTPException(status_code=500, detail="No API keys configured.")
        
        tried_keys = set()
        for _ in range(number_of_keys):
            if api_key in tried_keys:
                break
            tried_keys.add(api_key)
            try:
                await key_rate_limiter.check_and_reserve(model, api_key, estimated_tokens)
                break
            except RateLimitExceededError:
                api_key = await self.key_manager.get_next_working_key()
                continue
        else:
            raise RateLimitExceededError("All API keys are currently rate-limited for this model.")

        # --- API 调用 ---
        start_time = time.perf_counter()
        request_datetime = datetime.datetime.now()
        is_success = False
        status_code = None
        response = None
        try:
            # 全局速率限制 (旧模式，暂不修改为 reserve/adjust)
            await rate_limiter.reserve_tokens(model, estimated_tokens)
            response = await self.api_client.generate_content(request, api_key)
            is_success = True
            status_code = 200
            return response
        except Exception as e:
            is_success = False
            status_code = e.args[0]
            error_log_msg = e.args[1]
            logger.error(f"Normal API call failed with error: {error_log_msg}")

            # 判断是否是Google的配额耗尽错误
            is_resource_exhausted_error = (
                status_code == 429
                and "Resource has been exhausted" in error_log_msg
            )

            # 如果不是配额耗尽错误，才释放预留的资源
            if not is_resource_exhausted_error:
                await key_rate_limiter.release(model, api_key, estimated_tokens)

            await add_error_log(
                gemini_key=api_key,
                model_name=model,
                error_type="openai-compatiable-non-stream",
                error_log=error_log_msg,
                error_code=status_code,
                request_msg=request if settings.ERROR_LOG_RECORD_REQUEST_BODY else None,
            )
            raise e
        finally:
            # 兼容模式下无法精确计算 'actual_tokens'，因此只调整预估值
            # 成功则消耗，失败则已在 except 中通过 release 回滚
            await rate_limiter.adjust_token_count(model, estimated_tokens, estimated_tokens if is_success else 0)
            if is_success:
                 await key_rate_limiter.update_token_usage(model, api_key, estimated_tokens, estimated_tokens)

            end_time = time.perf_counter()
            latency_ms = int((end_time - start_time) * 1000)
            await add_request_log(
                model_name=model,
                api_key=api_key,
                is_success=is_success,
                status_code=status_code,
                latency_ms=latency_ms,
                request_time=request_datetime,
            )

    async def _handle_stream_completion(
        self, model: str, payload: dict, api_key: str
    ) -> AsyncGenerator[str, None]:
        """处理流式聊天完成"""
        estimated_tokens = estimate_payload_tokens(payload)

        # --- 查找可用密钥 ---
        if not self.key_manager:
            raise HTTPException(status_code=500, detail="KeyManager is not initialized.")
        number_of_keys = len(self.key_manager.api_keys)
        if number_of_keys == 0:
            raise HTTPException(status_code=500, detail="No API keys configured.")

        tried_keys = set()
        for _ in range(number_of_keys):
            if api_key in tried_keys:
                break
            tried_keys.add(api_key)
            try:
                await key_rate_limiter.check_and_reserve(model, api_key, estimated_tokens)
                break
            except RateLimitExceededError:
                api_key = await self.key_manager.get_next_working_key()
                continue
        else:
            raise RateLimitExceededError("All API keys are currently rate-limited for this model.")

        # --- API 调用 ---
        await rate_limiter.reserve_tokens(model, estimated_tokens)
        start_time = time.perf_counter()
        request_datetime = datetime.datetime.now()
        is_success = False
        status_code = None

        try:
            async for line in self.api_client.stream_generate_content(payload, api_key):
                if line.startswith("data:"):
                    yield line + "\n\n"
            is_success = True
            status_code = 200
        except Exception as e:
            await key_rate_limiter.release(model, api_key, estimated_tokens)
            is_success = False
            status_code = e.args[0]
            error_log_msg = e.args[1]
            logger.error(f"Streaming API call failed: {error_log_msg}")
            await add_error_log(
                gemini_key=api_key,
                model_name=model,
                error_type="openai-compatiable-stream",
                error_log=error_log_msg,
                error_code=status_code,
                request_msg=(payload if settings.ERROR_LOG_RECORD_REQUEST_BODY else None),
                request_datetime=request_datetime,
            )
            raise e
        finally:
            await rate_limiter.adjust_token_count(model, estimated_tokens, estimated_tokens if is_success else 0)
            if is_success:
                await key_rate_limiter.update_token_usage(model, api_key, estimated_tokens, estimated_tokens)
            
            end_time = time.perf_counter()
            latency_ms = int((end_time - start_time) * 1000)
            await add_request_log(
                model_name=model,
                api_key=api_key,
                is_success=is_success,
                status_code=status_code,
                latency_ms=latency_ms,
                request_time=request_datetime,
            )
