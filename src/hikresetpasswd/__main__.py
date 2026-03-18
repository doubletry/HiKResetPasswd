"""
程序入口点（用于直接运行或 Nuitka 编译）
Application entry point (for direct execution or Nuitka compilation).

使用方式 / Usage:
  python -m hikresetpasswd
  或编译后 / or compiled: ./hikresetpasswd
"""

import uvicorn

from hikresetpasswd.config import settings
from hikresetpasswd.main import app


def main() -> None:
    """启动 uvicorn 服务器 / Start the uvicorn server."""
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
