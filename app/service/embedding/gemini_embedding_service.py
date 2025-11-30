# app/service/embedding/gemini_embedding_service.py

import datetime
import time
from typing import Any, Dict

from app.config.config import settings
from app.database.services import add_error_log, add_request_log
import datetime
import time
from typing import Any, Dict

from app.config.config import settings
from app.database.services import add_error_log, add_request_log
from app.domain.gemini_models import GeminiBatchEmbedRequest, GeminiEmbedRequest
from fastapi import HTTPException
from app.handler.rate_limit_handler import rate_limiter
from app.log.logger import Logger
from app.service.client.api_client import GeminiApiClient
from app.service.key.key_manager import KeyManager
from app.utils.helpers import (
    estimate_payload_tokens,
    get_actual_tokens_from_response,
)

logger = Logger.setup_logger("gemini_embedding")


def _build_embed_payload(request: GeminiEmbedRequest) -> Dict[str, Any]:
    """构建嵌入请求payload"""
    payload = {"content": request.content.model_dump()}

    if request.taskType:
        payload["taskType"] = request.taskType
    if request.title:
        payload["title"] = request.title
    if request.outputDimensionality:
        payload["outputDimensionality"] = request.outputDimensionality

    return payload


def _build_batch_embed_payload(
    request: GeminiBatchEmbedRequest, model: str
) -> Dict[str, Any]:
    """构建批量嵌入请求payload"""
    requests = []
    for embed_request in request.requests:
        embed_payload = _build_embed_payload(embed_request)
        embed_payload["model"] = (
            f"models/{model}"  # Gemini API要求每个请求包含model字段
        )
        requests.append(embed_payload)

    return {"requests": requests}


class GeminiEmbeddingService:
    """Gemini嵌入服务"""

    def __init__(self, base_url: str, key_manager: KeyManager):
        self.api_client = GeminiApiClient(base_url, settings.TIME_OUT)
        self.key_manager = key_manager

    async def embed_content(
        self, model: str, request: GeminiEmbedRequest, api_key: str
    ) -> Dict[str, Any]:
        """生成单一嵌入内容"""
        payload = _build_embed_payload(request)

        estimated_tokens = estimate_payload_tokens(payload)
        await rate_limiter.reserve_tokens(model, estimated_tokens)

        start_time = time.perf_counter()
        request_datetime = datetime.datetime.now(datetime.timezone.utc)
        is_success = False
        status_code = None
        response = None
        actual_tokens = 0

        try:
            response = await self.api_client.embed_content(payload, model, api_key)
            is_success = True
            status_code = 200
        except Exception as e:
            is_success = False
            if isinstance(e, HTTPException):
                status_code = e.status_code
                error_log_msg = e.detail
            else:
                # Fallback for other exception types
                status_code = getattr(e, "status_code", 500)
                error_log_msg = str(e)

            logger.error(f"Single embedding API call failed: {status_code} - {error_log_msg}")
            await add_error_log(
                gemini_key=api_key,
                model_name=model,
                error_type="gemini-embed-single",
                error_log=error_log_msg,
                error_code=status_code,
                request_msg=payload if settings.ERROR_LOG_RECORD_REQUEST_BODY else None,
                request_datetime=request_datetime,
            )
            raise e
        finally:
            if response:
                actual_tokens = get_actual_tokens_from_response(response)
            await rate_limiter.adjust_token_count(
                model, estimated_tokens, actual_tokens
            )

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
        return response

    async def batch_embed_contents(
        self, model: str, request: GeminiBatchEmbedRequest, api_key: str
    ) -> Dict[str, Any]:
        """生成批量嵌入内容"""
        payload = _build_batch_embed_payload(request, model)

        estimated_tokens = estimate_payload_tokens(payload)
        await rate_limiter.reserve_tokens(model, estimated_tokens)

        start_time = time.perf_counter()
        request_datetime = datetime.datetime.now(datetime.timezone.utc)
        is_success = False
        status_code = None
        response = None
        actual_tokens = 0

        try:
            response = await self.api_client.batch_embed_contents(
                payload, model, api_key
            )
            is_success = True
            status_code = 200
        except Exception as e:
            is_success = False
            if isinstance(e, HTTPException):
                status_code = e.status_code
                error_log_msg = e.detail
            else:
                # Fallback for other exception types
                status_code = getattr(e, "status_code", 500)
                error_log_msg = str(e)

            logger.error(f"Batch embedding API call failed: {status_code} - {error_log_msg}")
            await add_error_log(
                gemini_key=api_key,
                model_name=model,
                error_type="gemini-embed-batch",
                error_log=error_log_msg,
                error_code=status_code,
                request_msg=payload if settings.ERROR_LOG_RECORD_REQUEST_BODY else None,
                request_datetime=request_datetime,
            )
            raise e
        finally:
            if response:
                actual_tokens = get_actual_tokens_from_response(response)
            await rate_limiter.adjust_token_count(
                model, estimated_tokens, actual_tokens
            )

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
        return response
