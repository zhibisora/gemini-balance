import base64
import json
import random
import string
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.config.config import settings
from app.log.logger import get_gemini_logger

logger = get_gemini_logger()


class ResponseHandler(ABC):
    """响应处理器基类"""

    @abstractmethod
    def handle_response(
        self, response: Dict[str, Any], model: str, stream: bool = False
    ) -> Dict[str, Any]:
        pass


class GeminiResponseHandler(ResponseHandler):
    """Gemini响应处理器"""

    def __init__(self):
        self.thinking_first = True
        self.thinking_status = False

    def handle_response(
        self,
        response: Dict[str, Any],
        model: str,
        stream: bool = False,
        usage_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if stream:
            return _handle_gemini_stream_response(response, model, stream)
        return _handle_gemini_normal_response(response, model, stream)


def _extract_result(
    response: Dict[str, Any],
    model: str,
    stream: bool = False,
) -> tuple[str, List[Dict[str, Any]], Optional[bool]]:
    text, tool_calls, thought = "", [], None

    if stream:
        if response.get("candidates"):
            candidate = response["candidates"][0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            if not parts:
                logger.warning("No parts found in stream response")
                return "", [], None

            if "text" in parts[0]:
                text = parts[0].get("text")
                if "thought" in parts[0]:
                    thought = parts[0].get("thought")
            elif "executableCode" in parts[0]:
                text = _format_code_block(parts[0]["executableCode"])
            elif "codeExecution" in parts[0]:
                text = _format_code_block(parts[0]["codeExecution"])
            elif "executableCodeResult" in parts[0]:
                text = _format_execution_result(parts[0]["executableCodeResult"])
            elif "codeExecutionResult" in parts[0]:
                text = _format_execution_result(parts[0]["codeExecutionResult"])
            elif "inlineData" in parts[0]:
                text = _extract_image_data(parts[0])
            else:
                text = ""
            text = _add_search_link_text(model, candidate, text)
            tool_calls = _extract_tool_calls(parts)
    else:
        if response.get("candidates"):
            candidate = response["candidates"][0]
            text = ""

            # 使用安全的访问方式
            content = candidate.get("content", {})

            if content and isinstance(content, dict):
                parts = content.get("parts", [])
                if parts:
                    for part in parts:
                        if "text" in part:
                            text += part["text"]
                            if "thought" in part and thought is None:
                                thought = part.get("thought")
                        elif "inlineData" in part:
                            text += _extract_image_data(part)
                else:
                    logger.warning(f"No parts found in content for model: {model}")
            else:
                logger.error(f"Invalid content structure for model: {model}")

            text = _add_search_link_text(model, candidate, text)

            # 安全地获取 parts 用于工具调用提取
            parts = candidate.get("content", {}).get("parts", [])
            tool_calls = _extract_tool_calls(parts)
        else:
            logger.warning(f"No candidates found in response for model: {model}")
            text = "暂无返回"

    return text, tool_calls, thought


def _has_inline_image_part(response: Dict[str, Any]) -> bool:
    try:
        for c in response.get("candidates", []):
            for p in c.get("content", {}).get("parts", []):
                if isinstance(p, dict) and ("inlineData" in p):
                    return True
    except Exception:
        return False
    return False


def _extract_image_data(part: dict) -> str:
    """始终将内联图像数据格式化为base64数据URL"""
    base64_data = part["inlineData"]["data"]
    mime_type = part["inlineData"]["mimeType"]
    return f"\n\n![image](data:{mime_type};base64,{base64_data})\n\n"


def _extract_tool_calls(
    parts: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """提取工具调用信息"""
    if not parts or not isinstance(parts, list):
        return []

    tool_calls = []
    for part in parts:
        if not part or not isinstance(part, dict):
            continue

        if "functionCall" not in part or not isinstance(part.get("functionCall"), dict):
            continue

        tool_calls.append(part)

    return tool_calls


def _handle_gemini_stream_response(
    response: Dict[str, Any], model: str, stream: bool
) -> Dict[str, Any]:
    # Early return raw Gemini response if no uploader configured and contains inline images
    if not is_image_upload_configured(settings) and _has_inline_image_part(response):
        return response

    text, tool_calls, thought = _extract_result(response, model, stream=stream)
    if tool_calls:
        content = {"parts": tool_calls, "role": "model"}
    else:
        part = {"text": text}
        if thought is not None:
            part["thought"] = thought
        content = {"parts": [part], "role": "model"}
    response["candidates"][0]["content"] = content
    return response


def _handle_gemini_normal_response(
    response: Dict[str, Any], model: str, stream: bool
) -> Dict[str, Any]:
    # Early return raw Gemini response if no uploader configured and contains inline images
    if not is_image_upload_configured(settings) and _has_inline_image_part(response):
        return response

    text, tool_calls, thought = _extract_result(response, model, stream=stream)
    parts = []
    if tool_calls:
        parts = tool_calls
    else:
        part = {"text": text}
        if thought is not None:
            part["thought"] = thought
        parts.append(part)
    content = {"parts": parts, "role": "model"}
    response["candidates"][0]["content"] = content
    return response


def _format_code_block(code_data: dict) -> str:
    """格式化代码块输出"""
    language = code_data.get("language", "").lower()
    code = code_data.get("code", "").strip()
    return f"""\n\n---\n\n【代码执行】\n```{language}\n{code}\n```\n"""


def _add_search_link_text(model: str, candidate: dict, text: str) -> str:
    if (
        settings.SHOW_SEARCH_LINK
        and model.endswith("-search")
        and "groundingMetadata" in candidate
        and "groundingChunks" in candidate["groundingMetadata"]
    ):
        grounding_chunks = candidate["groundingMetadata"]["groundingChunks"]
        text += "\n\n---\n\n"
        text += "**【引用来源】**\n\n"
        for _, grounding_chunk in enumerate(grounding_chunks, 1):
            if "web" in grounding_chunk:
                text += _create_search_link(grounding_chunk["web"])
        return text
    else:
        return text


def _create_search_link(grounding_chunk: dict) -> str:
    return f'\n- [{grounding_chunk["title"]}]({grounding_chunk["uri"]})'


def _format_execution_result(result_data: dict) -> str:
    """格式化执行结果输出"""
    outcome = result_data.get("outcome", "")
    output = result_data.get("output", "").strip()
    return f"""\n【执行结果】\n> outcome: {outcome}\n\n【输出结果】\n```plaintext\n{output}\n```\n\n---\n\n"""
