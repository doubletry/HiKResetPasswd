"""
应用配置模块 / Application configuration module.

从 .env 文件或系统环境变量中读取配置。
Reads configuration from a .env file or system environment variables.
"""

import os

from dotenv import load_dotenv

# 加载 .env 文件（如果存在则覆盖系统变量，否则忽略）
# Load .env file (overrides system env if present, silently ignored if absent)
load_dotenv(override=False)


class Settings:
    """
    应用程序设置，从环境变量中读取。
    Application settings read from environment variables.

    优先级 / Priority: 系统环境变量 > .env 文件 > 默认值
                       System env > .env file > defaults
    """

    #: 后端监听地址 / Backend bind host
    host: str = os.getenv("HOST", "0.0.0.0")

    #: 后端监听端口 / Backend port
    port: int = int(os.getenv("PORT", "8000"))

    #: 日志级别 / Log level
    log_level: str = os.getenv("LOG_LEVEL", "info").lower()

    #: CORS 允许的源地址列表 / CORS allowed origins list
    allowed_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")
        if origin.strip()
    ]

    #: 前端开发服务端口 / Frontend dev server port
    frontend_port: int = int(os.getenv("FRONTEND_PORT", "5173"))


# 全局单例 / Global singleton instance
settings = Settings()
