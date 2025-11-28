from typing import Optional, Tuple

from app.log.logger import get_update_logger

logger = get_update_logger()

async def check_for_updates() -> Tuple[bool, Optional[str], Optional[str]]:
    """
    通过比较当前版本与最新的 GitHub release 来检查应用程序更新。
    此功能已被禁用。

    Returns:
        Tuple[bool, Optional[str], Optional[str]]: 一个元组，包含：
            - bool: 如果有可用更新则为 True，否则为 False。
            - Optional[str]: 如果有可用更新，则为最新的版本字符串，否则为 None。
            - Optional[str]: 如果检查失败，则为错误消息，否则为 None。
    """
    logger.info("Update check is disabled.")
    return False, None, "Update check is disabled."