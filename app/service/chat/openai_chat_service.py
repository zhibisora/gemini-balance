# app/services/chat_service.py

import asyncio
import datetime
import json
import time
from copy import deepcopy
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from app.config.config import settings
from app.core.constants import GEMINI_2_FLASH_EXP_SAFETY_SETTINGS
from app.database.services import (
    add_error_log,
    add_request_log,
)
import asyncio
import datetime
import json
import time
from copy import deepcopy
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from app.config.config import settings
from app.core.constants import GEMINI_2_FLASH_EXP_SAFETY_SETTINGS
from app.database.services import (
    add_error_log,
    add_request_log,
)
from app.domain.openai_models import ChatRequest, ImageGenerationRequest
from app.handler.message_converter import OpenAIMessageConverter
from app.exception.exceptions import RateLimitExceededError
from app.handler.rate_limit_handler import key_rate_limiter, rate_limiter
from app.handler.response_handler import OpenAIResponseHandler
from app.handler.stream_optimizer import openai_optimizer
from app.log.logger import get_openai_logger
from app.service.client.api_client import GeminiApiClient
from app.service.image.image_create_service import ImageCreateService
from app.service.key.key_manager import KeyManager
from app.utils.helpers import (
    estimate_payload_tokens,
    get_actual_tokens_from_response,
)

logger = get_openai_logger()


def _has_media_parts(messages: List[Dict[str, Any]]) -> bool:
    """判断消息是否包含多媒体部分"""
    for message in messages:
        if "parts" in message:
            for part in message["parts"]:
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


def _build_tools(
    request: ChatRequest, messages: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """构建工具"""
    tool = dict()
    model = request.model

    if (
        settings.TOOLS_CODE_EXECUTION_ENABLED
        and not (
            model.endswith("-search")
            or "-thinking" in model
            or model.endswith("-image")
            or model.endswith("-image-generation")
        )
        and not _has_media_parts(messages)
    ):
        tool["codeExecution"] = {}
        logger.debug("Code execution tool enabled.")
    elif _has_media_parts(messages):
        logger.debug("Code execution tool disabled due to media parts presence.")

    if model.endswith("-search"):
        tool["googleSearch"] = {}

    real_model = _get_real_model(model)
    if real_model in settings.URL_CONTEXT_MODELS and settings.URL_CONTEXT_ENABLED:
        tool["urlContext"] = {}

    # 将 request 中的 tools 合并到 tools 中
    if request.tools:
        function_declarations = []
        for item in request.tools:
            if not item or not isinstance(item, dict):
                continue

            if item.get("type", "") == "function" and item.get("function"):
                function = deepcopy(item.get("function"))
                parameters = function.get("parameters", {})
                if parameters.get("type") == "object" and not parameters.get(
                    "properties", {}
                ):
                    function.pop("parameters", None)

                # 清理函数中的不支持字段
                function = _clean_json_schema_properties(function)
                function_declarations.append(function)

        if function_declarations:
            # 按照 function 的 name 去重
            names, functions = set(), []
            for fc in function_declarations:
                if fc.get("name") not in names:
                    if fc.get("name") == "googleSearch":
                        # cherry开启内置搜索时，添加googleSearch工具
                        tool["googleSearch"] = {}
                    else:
                        # 其他函数，添加到functionDeclarations中
                        names.add(fc.get("name"))
                        functions.append(fc)

            tool["functionDeclarations"] = functions

    # 解决 "Tool use with function calling is unsupported" 问题
    if tool.get("functionDeclarations"):
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
    # if (
    #     "2.0" in model
    #     and "gemini-2.0-flash-thinking-exp" not in model
    #     and "gemini-2.0-pro-exp" not in model
    # ):
    if model == "gemini-2.0-flash-exp":
        return GEMINI_2_FLASH_EXP_SAFETY_SETTINGS
    return settings.SAFETY_SETTINGS


def _validate_and_set_max_tokens(
    payload: Dict[str, Any], max_tokens: Optional[int], logger_instance
) -> None:
    """验证并设置 max_tokens 参数"""
    if max_tokens is None:
        return

    # 参数验证和处理
    if max_tokens <= 0:
        logger_instance.warning(
            f"Invalid max_tokens value: {max_tokens}, will not set maxOutputTokens"
        )
        # 不设置 maxOutputTokens，让 Gemini API 使用默认值
    else:
        payload["generationConfig"]["maxOutputTokens"] = max_tokens


def _build_payload(
    request: ChatRequest,
    messages: List[Dict[str, Any]],
    instruction: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建请求payload"""
    payload = {
        "contents": messages,
        "generationConfig": {
            "temperature": request.temperature,
            "stopSequences": request.stop,
            "topP": request.top_p,
            "topK": request.top_k,
        },
        "tools": _build_tools(request, messages),
        "safetySettings": _get_safety_settings(request.model),
    }

    # 处理 max_tokens 参数
    _validate_and_set_max_tokens(payload, request.max_tokens, logger)

    # 处理 n 参数
    if request.n is not None and request.n > 0:
        payload["generationConfig"]["candidateCount"] = request.n

    if request.model.endswith("-image") or request.model.endswith("-image-generation"):
        payload["generationConfig"]["responseModalities"] = ["Text", "Image"]

    if request.model.endswith("-non-thinking"):
        if "gemini-2.5-pro" in request.model:
            payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 128}
        else:
            payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}

    elif _get_real_model(request.model) in settings.THINKING_BUDGET_MAP:
        if settings.SHOW_THINKING_PROCESS:
            payload["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": settings.THINKING_BUDGET_MAP.get(request.model, 1000),
                "includeThoughts": True,
            }
        else:
            payload["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": settings.THINKING_BUDGET_MAP.get(request.model, 1000)
            }

    if (
        instruction
        and isinstance(instruction, dict)
        and instruction.get("role") == "system"
        and instruction.get("parts")
        and not request.model.endswith("-image")
        and not request.model.endswith("-image-generation")
    ):
        payload["systemInstruction"] = instruction

    return payload


class OpenAIChatService:
    """聊天服务"""

    def __init__(self, base_url: str, key_manager: KeyManager = None):
        self.message_converter = OpenAIMessageConverter()
        self.response_handler = OpenAIResponseHandler(config=None)
        self.api_client = GeminiApiClient(base_url, settings.TIME_OUT)
        self.key_manager = key_manager
        self.image_create_service = ImageCreateService()

    def _extract_text_from_openai_chunk(self, chunk: Dict[str, Any]) -> str:
        """从OpenAI响应块中提取文本内容"""
        if not chunk.get("choices"):
            return ""

        choice = chunk["choices"][0]
        if "delta" in choice and "content" in choice["delta"]:
            return choice["delta"]["content"]
        return ""

    def _create_char_openai_chunk(
        self, original_chunk: Dict[str, Any], text: str
    ) -> Dict[str, Any]:
        """创建包含指定文本的OpenAI响应块"""
        chunk_copy = json.loads(json.dumps(original_chunk))
        if chunk_copy.get("choices") and "delta" in chunk_copy["choices"][0]:
            chunk_copy["choices"][0]["delta"]["content"] = text
        return chunk_copy

    async def create_chat_completion(
        self,
        request: ChatRequest,
        api_key: str,
    ) -> Union[Dict[str, Any], AsyncGenerator[str, None]]:
        """创建聊天完成"""
        messages, instruction = self.message_converter.convert(
            request.messages, request.model
        )

        payload = _build_payload(request, messages, instruction)

        if request.stream:
            return self._handle_stream_completion(request.model, payload, api_key)
        return await self._handle_normal_completion(request.model, payload, api_key)

    async def _handle_normal_completion(
        self, model: str, payload: Dict[str, Any], api_key: str
    ) -> Dict[str, Any]:
        """处理普通聊天完成"""
        estimated_tokens = estimate_payload_tokens(payload)

        # --- 新增逻辑: 寻找一个未被速率限制的可用密钥 ---
        number_of_keys = len(self.key_manager.api_keys)
        if number_of_keys == 0:
            raise HTTPException(status_code=500, detail="No API keys configured.")

        tried_keys = set()
        for _ in range(number_of_keys):
            if api_key in tried_keys:
                break
            tried_keys.add(api_key)

            try:
                await key_rate_limiter.check_and_reserve(
                    model, api_key, estimated_tokens
                )
                logger.debug(
                    f"Key ...{api_key[-4:]} passed rate limit check for model {model}."
                )
                break  # 找到可用密钥，跳出循环
            except RateLimitExceededError as e:
                logger.warning(
                    f"Key ...{api_key[-4:]} is rate-limited for model {model}: {e}. Trying next key."
                )
                api_key = await self.key_manager.get_next_working_key()
                continue
        else:  # for-else 循环，如果没有 break 则执行
            raise HTTPException(
                status_code=429,
                detail="All API keys are currently rate-limited for this model. Please try again later.",
            )

        # 全局TPM速率限制：预留
        await rate_limiter.reserve_tokens(model, estimated_tokens)

        start_time = time.perf_counter()
        request_datetime = datetime.datetime.now()
        is_success = False
        status_code = None
        response = None
        actual_tokens = 0
        result = None

        try:
            response = await self.api_client.generate_content(payload, model, api_key)
            usage_metadata = response.get("usageMetadata", {})
            is_success = True
            status_code = 200

            result = self.response_handler.handle_response(
                response,
                model,
                stream=False,
                finish_reason="stop",
                usage_metadata=usage_metadata,
            )
        except Exception as e:
            # API调用失败，释放该密钥的预留资源
            await key_rate_limiter.release(model, api_key, estimated_tokens)
            is_success = False
            if hasattr(e, "args") and len(e.args) >= 2:
                status_code, error_log_msg = e.args[0], e.args[1]
            else:
                status_code, error_log_msg = 500, str(e)

            logger.error(f"API call failed for model {model}: {error_log_msg}")
            await add_error_log(
                gemini_key=api_key,
                model_name=model,
                error_type="openai-chat-non-stream",
                error_log=error_log_msg,
                error_code=status_code,
                request_msg=payload if settings.ERROR_LOG_RECORD_REQUEST_BODY else None,
                request_datetime=request_datetime,
            )
            raise
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

        return result

    async def _fake_stream_logic_impl(
        self, model: str, payload: Dict[str, Any], api_key: str
    ) -> AsyncGenerator[str, None]:
        """处理伪流式 (fake stream) 的核心逻辑"""
        logger.info(
            f"Fake streaming enabled for model: {model}. Calling non-streaming endpoint."
        )
        estimated_tokens = estimate_payload_tokens(payload)
        actual_tokens = 0
        response = None

        try:
            api_response_task = asyncio.create_task(
                self.api_client.generate_content(payload, model, api_key)
            )
            i = 0
            while not api_response_task.done():
                i += 1
                if i >= settings.FAKE_STREAM_EMPTY_DATA_INTERVAL_SECONDS:
                    i = 0
                    empty_chunk = self.response_handler.handle_response(
                        {}, model, stream=True, finish_reason="stop", usage_metadata=None
                    )
                    yield f"data: {json.dumps(empty_chunk)}\n\n"
                    logger.debug("Sent empty data chunk for fake stream heartbeat.")
                await asyncio.sleep(1)

            response = await api_response_task

            if response and response.get("candidates"):
                processed_response = self.response_handler.handle_response(
                    response,
                    model,
                    stream=True,
                    finish_reason="stop",
                    usage_metadata=response.get("usageMetadata", {}),
                )
                yield f"data: {json.dumps(processed_response)}\n\n"
                logger.info(f"Sent full response content for fake stream: {model}")
            else:
                error_message = "Failed to get response from model"
                if response and isinstance(response, dict) and response.get("error"):
                    error_details = response.get("error")
                    if isinstance(error_details, dict):
                        error_message = error_details.get("message", error_message)
                logger.error(
                    f"No candidates or error in response for fake stream model {model}: {response}"
                )
                error_chunk = self.response_handler.handle_response(
                    {}, model, stream=True, finish_reason="stop", usage_metadata=None
                )
                yield f"data: {json.dumps(error_chunk)}\n\n"

        finally:
            if response:
                actual_tokens = get_actual_tokens_from_response(response)
            await rate_limiter.adjust_token_count(
                model, estimated_tokens, actual_tokens
            )

    async def _real_stream_logic_impl(
        self, model: str, payload: Dict[str, Any], api_key: str
    ) -> AsyncGenerator[str, None]:
        """处理真实流式 (real stream) 的核心逻辑"""
        estimated_tokens = estimate_payload_tokens(payload)
        actual_tokens = 0
        last_chunk_with_usage = None
        is_success = False

        try:
            tool_call_flag = False
            usage_metadata = None
            async for line in self.api_client.stream_generate_content(
                payload, model, api_key
            ):
                if line.startswith("data:"):
                    chunk_str = line[6:]
                    if not chunk_str.strip():
                        continue
                    try:
                        chunk = json.loads(chunk_str)
                        if chunk.get("usageMetadata"):
                            last_chunk_with_usage = chunk
                        usage_metadata = chunk.get("usageMetadata", {})
                    except json.JSONDecodeError:
                        logger.error(
                            f"Failed to decode JSON from stream for model {model}: {chunk_str}"
                        )
                        continue

                    openai_chunk = self.response_handler.handle_response(
                        chunk,
                        model,
                        stream=True,
                        finish_reason=None,
                        usage_metadata=usage_metadata,
                    )
                    if openai_chunk:
                        text = self._extract_text_from_openai_chunk(openai_chunk)
                        if text and settings.STREAM_OPTIMIZER_ENABLED:
                            async for (
                                optimized_chunk
                            ) in openai_optimizer.optimize_stream_output(
                                text,
                                lambda t: self._create_char_openai_chunk(
                                    openai_chunk, t
                                ),
                                lambda c: f"data: {json.dumps(c)}\n\n",
                            ):
                                yield optimized_chunk
                        else:
                            if openai_chunk.get("choices") and openai_chunk[
                                "choices"
                            ][0].get("delta", {}).get("tool_calls"):
                                tool_call_flag = True
                            yield f"data: {json.dumps(openai_chunk)}\n\n"

            final_reason = "tool_calls" if tool_call_flag else "stop"
            yield f"data: {json.dumps(self.response_handler.handle_response({}, model, stream=True, finish_reason=final_reason, usage_metadata=usage_metadata))}\n\n"
            is_success = True

        finally:
            if last_chunk_with_usage:
                actual_tokens = get_actual_tokens_from_response(last_chunk_with_usage)
            # 调整全局TPM计数
            await rate_limiter.adjust_token_count(
                model, estimated_tokens, actual_tokens
            )
            # 如果调用成功，则根据实际token用量校正单个密钥的TPM计数
            if is_success:
                await key_rate_limiter.update_token_usage(
                    model, api_key, estimated_tokens, actual_tokens
                )

    async def _handle_stream_completion(
        self, model: str, payload: Dict[str, Any], api_key: str
    ) -> AsyncGenerator[str, None]:
        """处理流式聊天完成，添加速率限制、重试逻辑和假流式支持"""
        estimated_tokens = estimate_payload_tokens(payload)
        retries = 0
        max_retries = settings.MAX_RETRIES
        is_success = False
        status_code = None
        final_api_key = api_key

        while retries < max_retries:
            start_time = time.perf_counter()
            request_datetime = datetime.datetime.now()
            current_attempt_key = final_api_key

            try:
                stream_generator = None
                if settings.FAKE_STREAM_ENABLED:
                    logger.info(
                        f"Using fake stream logic for model: {model}, Attempt: {retries + 1}"
                    )
                    stream_generator = self._fake_stream_logic_impl(
                        model, payload, current_attempt_key
                    )
                else:
                    logger.info(
                        f"Using real stream logic for model: {model}, Attempt: {retries + 1}"
                    )
                    stream_generator = self._real_stream_logic_impl(
                        model, payload, current_attempt_key
                    )

                async for chunk_data in stream_generator:
                    yield chunk_data

                yield "data: [DONE]\n\n"
                logger.info(
                    f"Streaming completed successfully for model: {model}, FakeStream: {settings.FAKE_STREAM_ENABLED}, Attempt: {retries + 1}"
                )
                is_success = True
                status_code = 200
                break

            except Exception as e:
                retries += 1
                is_success = False
                status_code = e.args[0]
                error_log_msg = e.args[1]
                logger.warning(
                    f"Streaming API call failed with error: {error_log_msg}. Attempt {retries} of {max_retries} with key {current_attempt_key}"
                )

                await add_error_log(
                    gemini_key=current_attempt_key,
                    model_name=model,
                    error_type="openai-chat-stream",
                    error_log=error_log_msg,
                    error_code=status_code,
                    request_msg=(
                        payload if settings.ERROR_LOG_RECORD_REQUEST_BODY else None
                    ),
                    request_datetime=request_datetime,
                )

                if self.key_manager:
                    new_api_key = await self.key_manager.handle_api_failure(
                        current_attempt_key, retries
                    )
                    if new_api_key and new_api_key != current_attempt_key:
                        final_api_key = new_api_key
                        logger.info(
                            f"Switched to new API key for next attempt: {final_api_key}"
                        )
                    elif not new_api_key:
                        logger.error(
                            f"No valid API key available after {retries} retries, ceasing attempts for this request."
                        )
                        raise
                else:
                    logger.error(
                        "KeyManager not available, cannot switch API key. Ceasing attempts for this request."
                    )
                    break

                if retries >= max_retries:
                    logger.error(
                        f"Max retries ({max_retries}) reached for streaming model {model}."
                    )
                    raise
            finally:
                end_time = time.perf_counter()
                latency_ms = int((end_time - start_time) * 1000)
                await add_request_log(
                    model_name=model,
                    api_key=current_attempt_key,
                    is_success=is_success,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    request_time=request_datetime,
                )

    async def create_image_chat_completion(
        self, request: ChatRequest, api_key: str
    ) -> Union[Dict[str, Any], AsyncGenerator[str, None]]:

        image_generate_request = ImageGenerationRequest()
        image_generate_request.prompt = request.messages[-1]["content"]
        image_res = self.image_create_service.generate_images_chat(
            image_generate_request
        )

        if request.stream:
            return self._handle_stream_image_completion(
                request.model, image_res, api_key
            )
        else:
            return await self._handle_normal_image_completion(
                request.model, image_res, api_key
            )

    async def _handle_stream_image_completion(
        self, model: str, image_data: str, api_key: str
    ) -> AsyncGenerator[str, None]:
        logger.info(f"Starting stream image completion for model: {model}")
        start_time = time.perf_counter()
        request_datetime = datetime.datetime.now()
        is_success = False
        status_code = None

        try:
            if image_data:
                openai_chunk = self.response_handler.handle_image_chat_response(
                    image_data, model, stream=True, finish_reason=None
                )
                if openai_chunk:
                    # 提取文本内容
                    text = self._extract_text_from_openai_chunk(openai_chunk)
                    if text:
                        # 使用流式输出优化器处理文本输出
                        async for (
                            optimized_chunk
                        ) in openai_optimizer.optimize_stream_output(
                            text,
                            lambda t: self._create_char_openai_chunk(openai_chunk, t),
                            lambda c: f"data: {json.dumps(c)}\n\n",
                        ):
                            yield optimized_chunk
                    else:
                        # 如果没有文本内容（如图片URL等），整块输出
                        yield f"data: {json.dumps(openai_chunk)}\n\n"
            yield f"data: {json.dumps(self.response_handler.handle_response({}, model, stream=True, finish_reason='stop'))}\n\n"
            logger.info(
                f"Stream image completion finished successfully for model: {model}"
            )
            is_success = True
            status_code = 200
            yield "data: [DONE]\n\n"
        except Exception as e:
            is_success = False
            status_code = e.args[0]
            error_log_msg = e.args[1]
            logger.error(error_log_msg)
            await add_error_log(
                gemini_key=api_key,
                model_name=model,
                error_type="openai-image-stream",
                error_log=error_log_msg,
                error_code=status_code,
                request_msg=(
                    {"image_data_truncated": image_data[:1000]}
                    if settings.ERROR_LOG_RECORD_REQUEST_BODY
                    else None
                ),
                request_datetime=request_datetime,
            )
            raise
        finally:
            end_time = time.perf_counter()
            latency_ms = int((end_time - start_time) * 1000)
            logger.info(
                f"Stream image completion for model {model} took {latency_ms} ms. Success: {is_success}"
            )
            await add_request_log(
                model_name=model,
                api_key=api_key,
                is_success=is_success,
                status_code=status_code,
                latency_ms=latency_ms,
                request_time=request_datetime,
            )

    async def _handle_normal_image_completion(
        self, model: str, image_data: str, api_key: str
    ) -> Dict[str, Any]:
        logger.info(f"Starting normal image completion for model: {model}")
        start_time = time.perf_counter()
        request_datetime = datetime.datetime.now()
        is_success = False
        status_code = None
        result = None

        try:
            result = self.response_handler.handle_image_chat_response(
                image_data, model, stream=False, finish_reason="stop"
            )
            logger.info(
                f"Normal image completion finished successfully for model: {model}"
            )
            is_success = True
            status_code = 200
            return result
        except Exception as e:
            is_success = False
            status_code = e.args[0]
            error_log_msg = e.args[1]
            logger.error(error_log_msg)
            await add_error_log(
                gemini_key=api_key,
                model_name=model,
                error_type="openai-image-non-stream",
                error_log=error_log_msg,
                error_code=status_code,
                request_msg=(
                    {"image_data_truncated": image_data[:1000]}
                    if settings.ERROR_LOG_RECORD_REQUEST_BODY
                    else None
                ),
                request_datetime=request_datetime,
            )
            raise
        finally:
            end_time = time.perf_counter()
            latency_ms = int((end_time - start_time) * 1000)
            logger.info(
                f"Normal image completion for model {model} took {latency_ms} ms. Success: {is_success}"
            )
            await add_request_log(
                model_name=model,
                api_key=api_key,
                is_success=is_success,
                status_code=status_code,
                latency_ms=latency_ms,
                request_time=request_datetime,
            )
