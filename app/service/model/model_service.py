from typing import Any, Dict, Optional

from app.config.config import settings
from app.log.logger import Logger
from app.service.client.api_client import GeminiApiClient

logger = Logger.setup_logger("model")


class ModelService:
    async def get_gemini_models(self, api_key: str) -> Optional[Dict[str, Any]]:
        api_client = GeminiApiClient(base_url=settings.BASE_URL)
        gemini_models = await api_client.get_models(api_key)

        if gemini_models is None:
            logger.error("从 API 客户端获取模型列表失败。")
            return None

        try:
            filtered_models_list = []
            for model in gemini_models.get("models", []):
                model_id = model["name"].split("/")[-1]
                if model_id not in settings.FILTERED_MODELS:
                    filtered_models_list.append(model)
                else:
                    logger.debug(f"Filtered out model: {model_id}")

            gemini_models["models"] = filtered_models_list
            return gemini_models
        except Exception as e:
            logger.error(f"处理模型列表时出错: {e}")
            return None

    async def check_model_support(self, model: str) -> bool:
        if not model or not isinstance(model, str):
            return False

        model = model.strip()
        if model.endswith("-search"):
            model = model[:-7]
            return model in settings.SEARCH_MODELS
        if model.endswith("-image"):
            model = model[:-6]
            return model in settings.IMAGE_MODELS

        return model not in settings.FILTERED_MODELS
