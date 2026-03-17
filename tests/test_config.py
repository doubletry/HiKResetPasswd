"""
配置模块测试 / Tests for the config module.
"""

import os
from unittest.mock import patch


class TestSettings:
    """测试 Settings 类的环境变量读取 / Test Settings class env var reading."""

    def test_default_host(self):
        """默认主机应为 0.0.0.0 / Default host should be 0.0.0.0."""
        with patch.dict(os.environ, {}, clear=True):
            # Re-import to pick up clean env
            import importlib
            import hikresetpasswd.config as cfg
            importlib.reload(cfg)
            assert cfg.Settings.host == "0.0.0.0"

    def test_default_port(self):
        """默认端口应为 8000 / Default port should be 8000."""
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            import hikresetpasswd.config as cfg
            importlib.reload(cfg)
            assert cfg.Settings.port == 8000

    def test_custom_host_from_env(self):
        """从环境变量读取自定义主机 / Read custom host from env var."""
        with patch.dict(os.environ, {"HOST": "127.0.0.1"}):
            import importlib
            import hikresetpasswd.config as cfg
            importlib.reload(cfg)
            assert cfg.Settings.host == "127.0.0.1"

    def test_custom_port_from_env(self):
        """从环境变量读取自定义端口 / Read custom port from env var."""
        with patch.dict(os.environ, {"PORT": "9000"}):
            import importlib
            import hikresetpasswd.config as cfg
            importlib.reload(cfg)
            assert cfg.Settings.port == 9000

    def test_allowed_origins_split(self):
        """多个 CORS 来源应被正确拆分 / Multiple CORS origins should be split correctly."""
        with patch.dict(os.environ, {"ALLOWED_ORIGINS": "http://a.com,http://b.com"}):
            import importlib
            import hikresetpasswd.config as cfg
            importlib.reload(cfg)
            assert "http://a.com" in cfg.Settings.allowed_origins
            assert "http://b.com" in cfg.Settings.allowed_origins
            assert len(cfg.Settings.allowed_origins) == 2

    def test_log_level_default(self):
        """默认日志级别应为 info / Default log level should be info."""
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            import hikresetpasswd.config as cfg
            importlib.reload(cfg)
            assert cfg.Settings.log_level == "info"

    def test_log_level_from_env(self):
        """从环境变量读取日志级别 / Read log level from env var."""
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
            import importlib
            import hikresetpasswd.config as cfg
            importlib.reload(cfg)
            assert cfg.Settings.log_level == "debug"
