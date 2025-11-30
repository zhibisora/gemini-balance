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


def extract_mime_type_and_data(base64_string: str) -> Tuple[Optional[str], str]:
    """
    从 base64 字符串中提取 MIME 类型和数据

    Args:
        base64_string: 可能包含 MIME 类型信息的 base64 字符串

    Returns:
        tuple: (mime_type, encoded_data)
    """
    # 检查字符串是否以 "data:" 格式开始
    if base64_string.startswith("data:"):
        # 提取 MIME 类型和数据
        pattern = DATA_URL_PATTERN
        match = re.match(pattern, base64_string)
        if match:
            mime_type = (
                "image/jpeg" if match.group(1) == "image/jpg" else match.group(1)
            )
            encoded_data = match.group(2)
            return mime_type, encoded_data

    # 如果不是预期格式，假定它只是数据部分
    return None, base64_string


def convert_image_to_base64(url: str) -> str:
    """
    将图片URL转换为base64编码

    Args:
        url: 图片URL

    Returns:
        str: base64编码的图片数据

    Raises:
        Exception: 如果获取图片失败
    """
    response = requests.get(url)
    if response.status_code == 200:
        # 将图片内容转换为base64
        img_data = base64.b64encode(response.content).decode("utf-8")
        return img_data
    else:
        raise Exception(f"Failed to fetch image: {response.status_code}")


def format_json_response(data: Dict[str, Any], indent: int = 2) -> str:
    """
    格式化JSON响应

    Args:
        data: 要格式化的数据
        indent: 缩进空格数

    Returns:
        str: 格式化后的JSON字符串
    """
    return json.dumps(data, indent=indent, ensure_ascii=False)


def extract_image_urls_from_markdown(text: str) -> List[str]:
    """
    从Markdown文本中提取图片URL

    Args:
        text: Markdown文本

    Returns:
        List[str]: 图片URL列表
    """
    pattern = IMAGE_URL_PATTERN
    matches = re.findall(pattern, text)
    return [match[1] for match in matches]


def is_valid_api_key(key: str) -> bool:
    """
    检查API密钥格式是否有效

    Args:
        key: API密钥

    Returns:
        bool: 如果密钥格式有效则返回True
    """
    # 检查Gemini API密钥格式
    if key.startswith("AIza"):
        return len(key) >= 30

    # 检查OpenAI API密钥格式
    if key.startswith("sk-"):
        return len(key) >= 30

    return False


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


def is_image_upload_configured(settings: Settings) -> bool:
    """Return True only if a valid upload provider is selected and all required settings for that provider are present."""

    provider = (getattr(settings, "UPLOAD_PROVIDER", "") or "").strip().lower()
    if provider == "smms":
        return bool(getattr(settings, "SMMS_SECRET_TOKEN", ""))
    if provider == "picgo":
        return bool(getattr(settings, "PICGO_API_KEY", ""))
    if provider == "aliyun_oss":
        return all(
            [
                getattr(settings, "OSS_ACCESS_KEY", ""),
                getattr(settings, "OSS_ACCESS_KEY_SECRET", ""),
                getattr(settings, "OSS_BUCKET_NAME", ""),
                getattr(settings, "OSS_ENDPOINT", ""),
                getattr(settings, "OSS_REGION", "")
            ]
        )
    if provider == "cloudflare_imgbed":
        return all(
            [
                getattr(settings, "CLOUDFLARE_IMGBED_URL", ""),
                getattr(settings, "CLOUDFLARE_IMGBED_AUTH_CODE", ""),
            ]
        )
    return False


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
