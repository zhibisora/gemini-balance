from typing import Any, Dict, Optional

from app.config import settings
from app.logger import Logger
from app.api_client import GeminiApiClient

logger = Logger.setup_logger("model")


class ModelService:
    async def get_gemini_models(self, api_key: str) -> Optional[Dict[str, Any]]:
        api_client = GeminiApiClient(base_url=settings.BASE_URL)
        gemini_models = await api_client.get_models(api_key)

        if gemini_models is None:
            logger.error("从 API 客户端获取模型列表失败。")
            return None

        return gemini_models

    async def check_model_support(self, model: str) -> bool:
        # 将模型有效性验证完全交给Gemini API
        return True
