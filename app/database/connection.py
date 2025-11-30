"""
数据库连接池模块
"""
from pathlib import Path
from urllib.parse import quote_plus
from databases import Database
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.declarative import declarative_base

from app.config.config import settings
from app.log.logger import Logger

logger = Logger.setup_logger("database")

# 数据库URL
DATABASE_URL = (
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{quote_plus(settings.POSTGRES_PASSWORD)}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)

# 创建数据库引擎
# pool_pre_ping=True: 在从连接池获取连接前执行简单的 "ping" 测试，确保连接有效
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)

# 创建元数据对象
metadata = MetaData()

# 创建基类
Base = declarative_base(metadata=metadata)

# 创建数据库连接池，并配置连接池参数，在sqlite中不使用连接池
# min_size/max_size: 连接池的最小/最大连接数
# max_inactive_connection_lifetime=1800: 非活动连接在池中保持的最长秒数。
#                    设置为 1800 秒（30分钟），以回收空闲连接并防止网络问题导致的连接失效。
# databases 库会自动处理连接失效后的重连尝试。
database = Database(
    DATABASE_URL, min_size=5, max_size=20, max_inactive_connection_lifetime=1800
)

async def connect_to_db():
    """
    连接到数据库
    """
    try:
        await database.connect()
        logger.info("Connected to PostgreSQL")
    except Exception as e:
        logger.error(f"Failed to connect to database: {str(e)}")
        raise


async def disconnect_from_db():
    """
    断开数据库连接
    """
    try:
        await database.disconnect()
        logger.info("Disconnected from PostgreSQL")
    except Exception as e:
        logger.error(f"Failed to disconnect from database: {str(e)}")
