"""
数据库初始化模块
"""
from dotenv import dotenv_values
from sqlalchemy import insert, select, inspect

from app.database.connection import Base, database, engine
from app.database.models import Settings
from app.log.logger import Logger

logger = Logger.setup_logger("database")


async def create_tables():
    """
    创建数据库表
    """
    try:
        async with engine.begin() as conn:
            # 创建所有表
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create database tables: {str(e)}")
        raise


async def import_env_to_settings():
    """
    将.env文件中的配置项导入到t_settings表中
    """
    try:
        # 获取.env文件中的所有配置项
        env_values = dotenv_values(".env")

        # 检查t_settings表是否存在
        async with engine.connect() as conn:
            table_exists = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).has_table("t_settings")
            )

        if table_exists:
            # 获取所有现有的配置项
            query = select(Settings.key)
            existing_rows = await database.fetch_all(query)
            current_keys = {row["key"] for row in existing_rows}

            settings_to_insert = []
            # 遍历所有配置项
            for key, value in env_values.items():
                # 检查配置项是否已存在
                if key not in current_keys:
                    settings_to_insert.append({"key": key, "value": value})

            if settings_to_insert:
                insert_query = insert(Settings).values(settings_to_insert)
                await database.execute(insert_query)
                logger.info(
                    f"Inserted {len(settings_to_insert)} new settings from .env file."
                )

        logger.info("Environment variables imported to settings table successfully")
    except Exception as e:
        logger.error(
            f"Failed to import environment variables to settings table: {str(e)}"
        )
        raise


async def initialize_database():
    """
    初始化数据库
    """
    try:
        # 创建表
        await create_tables()

        # 导入环境变量
        await import_env_to_settings()
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        raise
