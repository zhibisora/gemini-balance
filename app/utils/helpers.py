"""
通用工具函数模块
"""

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.config.config import Settings
from app.core.constants import DATA_URL_PATTERN, IMAGE_URL_PATTERN

helper_logger = logging.getLogger("app.utils")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VERSION_FILE_PATH = PROJECT_ROOT / "VERSION"


def redact_key_for_logging(key: str) -> str:
    """
    Redacts API key for secure logging by showing only first and last 6 characters.

    Args:
        key: API key to redact

    Returns:
        str: Redacted key in format "first6...last6" or descriptive placeholder for edge cases
    """
    if not key:
        return key

    if len(key) <= 12:
        return f"{key[:3]}...{key[-3:]}"
    else:
        return f"{key[:6]}...{key[-6:]}"


def get_current_version(default_version: str = "0.0.0") -> str:
    """Reads the current version from the VERSION file."""
    version_file = VERSION_FILE_PATH
    try:
        with version_file.open("r", encoding="utf-8") as f:
            version = f.read().strip()
        if not version:
            helper_logger.warning(
                f"VERSION file ('{version_file}') is empty. Using default version '{default_version}'."
            )
            return default_version
        return version
    except FileNotFoundError:
        helper_logger.warning(
            f"VERSION file not found at '{version_file}'. Using default version '{default_version}'."
        )
        return default_version
    except IOError as e:
        helper_logger.error(
            f"Error reading VERSION file ('{version_file}'): {e}. Using default version '{default_version}'."
        )
        return default_version


def estimate_payload_tokens(payload: Dict[str, Any]) -> int:
    """
    估算请求负载的token数。
    此函数采用混合方法：
    - 中文字符按 1 个字符计为 1 个 token。
    - 其他字符（如英文、数字）按 4 个字符计为 1 个 token。
    这是一个比单纯基于字符数更准确的估算方法，尤其适用于多语言内容。
    """
    total_tokens = 0.0

    def count_tokens_for_text(text: str):
        """计算给定文本字符串的估算token数并累加。"""
        nonlocal total_tokens
        if not isinstance(text, str):
            return

        chinese_chars = 0
        other_chars = 0

        for char in text:
            # 使用Unicode范围判断是否为中文字符
            if "\u4e00" <= char <= "\u9fff":
                chinese_chars += 1
            else:
                other_chars += 1

        total_tokens += chinese_chars  # 中文字符 1:1
        total_tokens += other_chars / 4.0  # 其他字符 4:1

    def extract_text_from_parts(parts: List[Dict[str, Any]]):
        if not isinstance(parts, list):
            return
        for part in parts:
            if isinstance(part, dict) and "text" in part and isinstance(part["text"], str):
                count_tokens_for_text(part["text"])

    # 处理 Gemini 聊天/嵌入负载 ('contents')
    contents = payload.get("contents")
    if isinstance(contents, list):
        for content_item in contents:
            if isinstance(content_item, dict):
                extract_text_from_parts(content_item.get("parts", []))

    # 处理 Gemini 批量嵌入负载 ('requests')
    requests = payload.get("requests")
    if isinstance(requests, list):
        for request_item in requests:
            if isinstance(request_item, dict):
                content = request_item.get("content", {})
                extract_text_from_parts(content.get("parts", []))

    # 处理 OpenAI 聊天负载 ('messages')
    messages = payload.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict):
                msg_content = message.get("content")
                if isinstance(msg_content, str):
                    count_tokens_for_text(msg_content)
                elif isinstance(msg_content, list):  # 处理多模态内容
                    for part in msg_content:
                        if part.get("type") == "text" and isinstance(part.get("text"), str):
                            count_tokens_for_text(part["text"])

    return max(int(total_tokens), 1)  # 向下取整并确保至少返回1


def get_actual_tokens_from_response(response: Dict[str, Any]) -> int:
    """从API响应中安全地提取实际的总token数。"""
    if not isinstance(response, dict):
        return 0

    # 检查 OpenAI 兼容格式
    usage = response.get("usage")
    if isinstance(usage, dict) and "total_tokens" in usage:
        return usage.get("total_tokens", 0)

    # 检查 Gemini API 格式
    usage_metadata = response.get("usageMetadata")
    if isinstance(usage_metadata, dict) and "totalTokenCount" in usage_metadata:
        return usage_metadata.get("totalTokenCount", 0)

    return 0
