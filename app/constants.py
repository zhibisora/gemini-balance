"""
常量定义模块
"""

# API相关常量
API_VERSION = "v1beta"
DEFAULT_TIMEOUT = 300  # 秒
MAX_RETRIES = 3  # 最大重试次数

# 模型相关常量
SUPPORTED_ROLES = ["user", "model", "system"]
DEFAULT_MODEL = "gemini-2.5-flash-lite"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 8192
DEFAULT_TOP_P = 0.9
DEFAULT_TOP_K = 40

# 正则表达式模式
IMAGE_URL_PATTERN = r"!\[(.*?)\]\((.*?)\)"
DATA_URL_PATTERN = r"data:([^;]+);base64,(.+)"