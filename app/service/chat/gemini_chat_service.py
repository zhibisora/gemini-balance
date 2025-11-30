# app/services/chat_service.py

import datetime
import json
import re
import time
from typing import Any, AsyncGenerator, Dict, List

from app.config.config import settings
from app.core.constants import GEMINI_2_FLASH_EXP_SAFETY_SETTINGS
from app.database.services import add_error_log, add_request_log
import datetime
import json
import re
import time
from typing import Any, AsyncGenerator, Dict, List

from app.config.config import settings
from app.core.constants import GEMINI_2_FLASH_EXP_SAFETY_SETTINGS
from app.database.services import add_error_log, add_request_log
from fastapi import HTTPException

from app.domain.gemini_models import GeminiRequest
from app.exception.exceptions import RateLimitExceededError, RequestTooLargeError
from app.handler.rate_limit_handler import key_rate_limiter, rate_limiter
from app.handler.response_handler import GeminiResponseHandler
from app.log.logger import get_gemini_logger
from app.service.client.api_client import GeminiApiClient
from app.service.key.key_manager import KeyManager
from app.utils.helpers import (
    estimate_payload_tokens,
    get_actual_tokens_from_response,
    redact_key_for_logging,
)

logger = get_gemini_logger()


def _has_image_parts(contents: List[Dict[str, Any]]) -> bool:
    """判断消息是否包含图片部分"""
    for content in contents:
        if "parts" in content:
            for part in content["parts"]:
                if "image_url" in part or "inline_data" in part:
                    return True
    return False


def _clean_json_schema_properties(obj: Any) -> Any:
    """清理JSON Schema中Gemini API不支持的字段"""
    if not isinstance(obj, dict):
        return obj

    # Gemini API不支持的JSON Schema字段
    unsupported_fields = {
        "exclusiveMaximum",
        "exclusiveMinimum",
        "const",
        "examples",
        "contentEncoding",
        "contentMediaType",
        "if",
        "then",
        "else",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "definitions",
        "$schema",
        "$id",
        "$ref",
        "$comment",
        "readOnly",
        "writeOnly",
    }

    cleaned = {}
    for key, value in obj.items():
        if key in unsupported_fields:
            continue
        if isinstance(value, dict):
            cleaned[key] = _clean_json_schema_properties(value)
        elif isinstance(value, list):
            cleaned[key] = [_clean_json_schema_properties(item) for item in value]
        else:
            cleaned[key] = value

    return cleaned


def _build_tools(model: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """构建工具"""

    def _has_function_call(contents: List[Dict[str, Any]]) -> bool:
        """检查内容中是否包含 functionCall"""
        if not contents or not isinstance(contents, list):
            return False
        for content in contents:
            if not content or not isinstance(content, dict) or "parts" not in content:
                continue
            parts = content.get("parts", [])
            if not parts or not isinstance(parts, list):
                continue
            for part in parts:
                if isinstance(part, dict) and "functionCall" in part:
                    return True
        return False

    def _merge_tools(tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        record = dict()
        for item in tools:
            if not item or not isinstance(item, dict):
                continue

            for k, v in item.items():
                if k == "functionDeclarations" and v and isinstance(v, list):
                    functions = record.get("functionDeclarations", [])
                    # 清理每个函数声明中的不支持字段
                    cleaned_functions = []
                    for func in v:
                        if isinstance(func, dict):
                            cleaned_func = _clean_json_schema_properties(func)
                            cleaned_functions.append(cleaned_func)
                        else:
                            cleaned_functions.append(func)
                    functions.extend(cleaned_functions)
                    record["functionDeclarations"] = functions
                else:
                    record[k] = v
        return record

    def _is_structured_output_request(payload: Dict[str, Any]) -> bool:
        """检查请求是否要求结构化JSON输出"""
        try:
            generation_config = payload.get("generationConfig", {})
            return generation_config.get("responseMimeType") == "application/json"
        except (AttributeError, TypeError):
            return False

    tool = dict()
    if payload and isinstance(payload, dict) and "tools" in payload:
        if payload.get("tools") and isinstance(payload.get("tools"), dict):
            payload["tools"] = [payload.get("tools")]
        items = payload.get("tools", [])
        if items and isinstance(items, list):
            tool.update(_merge_tools(items))

    # "Tool use with a response mime type: 'application/json' is unsupported"
    # Gemini API限制：不支持同时使用tools和结构化输出(response_mime_type='application/json')
    # 当请求指定了JSON响应格式时，跳过所有工具的添加以避免API错误
    has_structured_output = _is_structured_output_request(payload)
    if not has_structured_output:
        if (
            settings.TOOLS_CODE_EXECUTION_ENABLED
            and not (model.endswith("-search") or "-thinking" in model)
            and not _has_image_parts(payload.get("contents", []))
        ):
            tool["codeExecution"] = {}

        if model.endswith("-search"):
            tool["googleSearch"] = {}

        real_model = _get_real_model(model)
        if real_model in settings.URL_CONTEXT_MODELS and settings.URL_CONTEXT_ENABLED:
            tool["urlContext"] = {}

    # 解决 "Tool use with function calling is unsupported" 问题
    if tool.get("functionDeclarations") or _has_function_call(
        payload.get("contents", [])
    ):
        tool.pop("googleSearch", None)
        tool.pop("codeExecution", None)
        tool.pop("urlContext", None)

    return [tool] if tool else []


def _get_real_model(model: str) -> str:
    if model.endswith("-search"):
        model = model[:-7]
    if model.endswith("-image"):
        model = model[:-6]
    if model.endswith("-non-thinking"):
        model = model[:-13]
    if "-search" in model and "-non-thinking" in model:
        model = model[:-20]
    return model


def _get_safety_settings(model: str) -> List[Dict[str, str]]:
    """获取安全设置"""
    if model == "gemini-2.0-flash-exp":
        return GEMINI_2_FLASH_EXP_SAFETY_SETTINGS
    return settings.SAFETY_SETTINGS


def _filter_empty_parts(contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filters out contents with empty or invalid parts."""
    if not contents:
        return []

    filtered_contents = []
    for content in contents:
        if (
            not content
            or "parts" not in content
            or not isinstance(content.get("parts"), list)
        ):
            continue

        valid_parts = [
            part for part in content["parts"] if isinstance(part, dict) and part
        ]

        if valid_parts:
            new_content = content.copy()
            new_content["parts"] = valid_parts
            filtered_contents.append(new_content)

    return filtered_contents


def _build_payload(model: str, request: GeminiRequest) -> Dict[str, Any]:
    """构建请求payload"""
    request_dict = request.model_dump(exclude_none=False)
    if request.generationConfig:
        if request.generationConfig.maxOutputTokens is None:
            # 如果未指定最大输出长度，则不传递该字段，解决截断的问题
            if "maxOutputTokens" in request_dict["generationConfig"]:
                request_dict["generationConfig"].pop("maxOutputTokens")

    # 非TTS模型使用完整的payload
    payload = {
        "contents": _filter_empty_parts(request_dict.get("contents", [])),
        "tools": _build_tools(model, request_dict),
        "safetySettings": _get_safety_settings(model),
        "generationConfig": request_dict.get("generationConfig"),
        "systemInstruction": request_dict.get("systemInstruction"),
    }

    # 确保 generationConfig 不为 None
    if payload["generationConfig"] is None:
        payload["generationConfig"] = {}

    if model.endswith("-image") or model.endswith("-image-generation"):
        payload.pop("systemInstruction")
        payload["generationConfig"]["responseModalities"] = ["Text", "Image"]

    # 处理思考配置：优先使用客户端提供的配置，否则使用默认配置
    client_thinking_config = None
    if request.generationConfig and request.generationConfig.thinkingConfig:
        client_thinking_config = request.generationConfig.thinkingConfig

    if client_thinking_config is not None:
        # 客户端提供了思考配置，直接使用
        payload["generationConfig"]["thinkingConfig"] = client_thinking_config
    else:
        # 客户端没有提供思考配置，使用默认配置
        if model.endswith("-non-thinking"):
            if "gemini-2.5-pro" in model:
                payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 128}
            else:
                payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
        elif _get_real_model(model) in settings.THINKING_BUDGET_MAP:
            if settings.SHOW_THINKING_PROCESS:
                payload["generationConfig"]["thinkingConfig"] = {
                    "thinkingBudget": settings.THINKING_BUDGET_MAP.get(model, 1000),
                    "includeThoughts": True,
                }
            else:
                payload["generationConfig"]["thinkingConfig"] = {
                    "thinkingBudget": settings.THINKING_BUDGET_MAP.get(model, 1000)
                }

    return payload


class GeminiChatService:
    """聊天服务"""

    def __init__(self, base_url: str, key_manager: KeyManager):
        self.api_client = GeminiApiClient(base_url, settings.TIME_OUT)
        self.key_manager = key_manager
        self.response_handler = GeminiResponseHandler()

    async def _select_key_and_apply_rate_limits(
        self, model: str, estimated_tokens: int, initial_api_key: str
    ) -> str:
        """
        选择一个可用的API密钥，检查其独立速率限制，然后预留全局TPM限制的令牌。
        返回选定的密钥。
        如果超出限制，则引发 RateLimitExceededError 或 RequestTooLargeError。
        """
        number_of_keys = len(self.key_manager.api_keys)
        if number_of_keys == 0:
            raise HTTPException(status_code=500, detail="No API keys configured.")

        api_key = initial_api_key
        tried_keys = set()
        # 循环次数等于可用密钥数量，以确保每个密钥最多尝试一次
        for _ in range(number_of_keys):
            if api_key in tried_keys:
                api_key = await self.key_manager.get_next_working_key()
                continue  # 跳过以检查新获取的密钥

            tried_keys.add(api_key)

            try:
                # 检查单个密钥的速率限制
                await key_rate_limiter.check_and_reserve(
                    model, api_key, estimated_tokens
                )
                logger.debug(
                    f"Key ...{api_key[-4:]} passed individual rate limit check for model {model}."
                )

                # 检查并预留全局TPM速率限制
                await rate_limiter.reserve_tokens(model, estimated_tokens)
                logger.debug(f"Global TPM rate limit passed for model {model}.")

                # 如果两个检查都通过，我们找到了一个有效的密钥
                return api_key

            except RequestTooLargeError as e:
                # 如果请求太大，尝试其他密钥也无济于事。快速失败。
                logger.error(
                    f"Request rejected due to excessive tokens ({estimated_tokens}), not trying other keys: {e.detail}"
                )
                raise e
            except RateLimitExceededError as e:
                # 此密钥受到速率限制，记录并尝试下一个。
                logger.warning(
                    f"Key ...{api_key[-4:]} is rate-limited for model {model}: {e}. Trying next key."
                )
                api_key = await self.key_manager.get_next_working_key()
                continue

        # 如果循环完成而没有返回，则表示所有密钥都已尝试过且均受到速率限制。
        raise RateLimitExceededError(
            "All available API keys are currently rate-limited for this model. Please try again later."
        )

    async def generate_content(
        self, model: str, request: GeminiRequest, api_key: str
    ) -> Dict[str, Any]:
        """生成内容"""
        payload = _build_payload(model, request)
        estimated_tokens = estimate_payload_tokens(payload)

        api_key = await self._select_key_and_apply_rate_limits(
            model, estimated_tokens, api_key
        )

        start_time = time.perf_counter()
        request_datetime = datetime.datetime.now()
        is_success = False
        status_code = None
        response = None
        actual_tokens = 0
        processed_response = None

        try:
            response = await self.api_client.generate_content(payload, model, api_key)
            is_success = True
            status_code = 200
            processed_response = self.response_handler.handle_response(
                response, model, stream=False
            )
        except Exception as e:
            # API调用失败，释放该密钥的预留资源
            await key_rate_limiter.release(model, api_key, estimated_tokens)
            is_success = False
            if isinstance(e, HTTPException):
                status_code = e.status_code
                error_log_msg = e.detail
            else:
                # Fallback for other exception types
                status_code = getattr(e, "status_code", 500)
                error_log_msg = str(e)

            logger.error(f"Normal API call failed with error: {status_code} - {error_log_msg}")

            await add_error_log(
                gemini_key=api_key,
                model_name=model,
                error_type="gemini-chat-non-stream",
                error_log=error_log_msg,
                error_code=status_code,
                request_msg=payload if settings.ERROR_LOG_RECORD_REQUEST_BODY else None,
                request_datetime=request_datetime,
            )
            raise e
        finally:
            if response:
                actual_tokens = get_actual_tokens_from_response(response)

            # 调整全局TPM计数
            await rate_limiter.adjust_token_count(
                model, estimated_tokens, actual_tokens
            )

            # 如果调用成功，则根据实际token用量校正单个密钥的TPM计数
            if is_success:
                await key_rate_limiter.update_token_usage(
                    model, api_key, estimated_tokens, actual_tokens
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
        return processed_response

    async def count_tokens(
        self, model: str, request: GeminiRequest, api_key: str
    ) -> Dict[str, Any]:
        """计算token数量"""
        # countTokens API只需要contents
        payload = {
            "contents": _filter_empty_parts(request.model_dump().get("contents", []))
        }
        start_time = time.perf_counter()
        request_datetime = datetime.datetime.now()
        is_success = False
        status_code = None
        response = None

        try:
            response = await self.api_client.count_tokens(payload, model, api_key)
            is_success = True
            status_code = 200
            return response
        except Exception as e:
            is_success = False
            if isinstance(e, HTTPException):
                status_code = e.status_code
                error_log_msg = e.detail
            else:
                # Fallback for other exception types
                status_code = getattr(e, "status_code", 500)
                error_log_msg = str(e)

            logger.error(f"Count tokens API call failed with error: {status_code} - {error_log_msg}")

            await add_error_log(
                gemini_key=api_key,
                model_name=model,
                error_type="gemini-count-tokens",
                error_log=error_log_msg,
                error_code=status_code,
                request_msg=payload if settings.ERROR_LOG_RECORD_REQUEST_BODY else None,
            )
            raise e
        finally:
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

    async def stream_generate_content(
        self, model: str, request: GeminiRequest, api_key: str
    ) -> AsyncGenerator[str, None]:
        """流式生成内容"""
        payload = _build_payload(model, request)
        estimated_tokens = estimate_payload_tokens(payload)

        # --- 寻找一个未被速率限制的可用密钥 ---
        number_of_keys = len(self.key_manager.api_keys)
        if number_of_keys == 0:
            raise HTTPException(status_code=500, detail="No API keys configured.")

        tried_keys = set()
        initial_api_key = api_key
        for _ in range(number_of_keys):
            if api_key in tried_keys and api_key != initial_api_key:
                api_key = await self.key_manager.get_next_working_key()
                continue
            tried_keys.add(api_key)

            try:
                await key_rate_limiter.check_and_reserve(
                    model, api_key, estimated_tokens
                )
                logger.debug(
                    f"Key ...{api_key[-4:]} passed rate limit check for model {model}."
                )
                break
            except RequestTooLargeError as e:
                logger.error(
                    f"请求因Token数量过大而被拒绝，不再尝试其他密钥: {e.detail}"
                )
                raise e
            except RateLimitExceededError as e:
                logger.warning(
                    f"Key ...{api_key[-4:]} is rate-limited for model {model}: {e}. Trying next key."
                )
                api_key = await self.key_manager.get_next_working_key()
                continue
        else:
            raise RateLimitExceededError(
                "All API keys are currently rate-limited for this model. Please try again later."
            )

        await rate_limiter.reserve_tokens(model, estimated_tokens)

        actual_tokens = 0
        last_chunk_with_usage = None
        is_success = False
        status_code = None
        start_time = time.perf_counter()
        request_datetime = datetime.datetime.now()

        try:
            async for line in self.api_client.stream_generate_content(
                payload, model, api_key
            ):
                if line.startswith("data:"):
                    line_data = line[6:]
                    if line_data.strip():
                        chunk_json = json.loads(line_data)
                        if chunk_json.get("usageMetadata"):
                            last_chunk_with_usage = chunk_json

                        response_data = self.response_handler.handle_response(
                            chunk_json, model, stream=True
                        )
                        yield "data: " + json.dumps(response_data) + "\n\n"
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

            logger.error(f"Streaming API call failed: {status_code} - {error_log_msg}")

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
                error_type="gemini-chat-stream",
                error_log=error_log_msg,
                error_code=status_code,
                request_msg=(
                    payload if settings.ERROR_LOG_RECORD_REQUEST_BODY else None
                ),
                request_datetime=request_datetime,
            )
            raise e
        finally:
            if last_chunk_with_usage:
                actual_tokens = get_actual_tokens_from_response(last_chunk_with_usage)

            await rate_limiter.adjust_token_count(
                model, estimated_tokens, actual_tokens
            )

            if is_success:
                await key_rate_limiter.update_token_usage(
                    model, api_key, estimated_tokens, actual_tokens
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