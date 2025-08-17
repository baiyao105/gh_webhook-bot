"""
配置管理
"""

import json
import os
from typing import Any, Dict, List, Optional

from filelock import FileLock
from loguru import logger
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
LOCK_DIR = os.path.join(os.path.dirname(__file__), "locks")
os.makedirs(LOCK_DIR, exist_ok=True)

# 默认配置
DEFAULT_CONFIG = {
    "port": 5080,
    "auto_start": False,
    "aggregation_delay": 5,
    "max_retry_attempts": 3,
    "retry_delay": 2,
    "image_cache_days": 4,
    "cache_cleanup_interval": 24,
    "forward_threshold": 1,
    "proxy": {"enabled": False, "url": "http://127.0.0.1:7897"},
    "debug_channel": {"enabled": True, "group_id": None},
    "star_milestones": {
        "enabled": True,
        "targets": [100, 200, 300, 400, 500, 600, 666, 700, 800, 900, 1000],
    },
    "user_mappings": {},  # GitHub用户名到QQ号的映射
    "repo_mappings": {
        "example/repo": {
            "alias": "示例仓库",
            "enabled": True,
            "qq_group_ids": [123456789],
            "webhook_secret": "",  # 每个仓库可以有独立的密钥
            "verify_signature": True,
            "allow_review": {"enabled": False, "bot_username": ""},
            "auto_tag": True,  # 是否启用自动标签
            "notification_channels": ["qq"],  # 通知渠道
            "allowed_message_types": [  # 允许发送的消息类型
                "push",
                "pull_request",
                "issues",
                "release",
                "star",
                "fork",
                "watch",
                "create",
                "delete",
                "workflow_run",
                "issue_comment",
                "pull_request_review",
                "pull_request_review_comment",
            ],
        }
    },
    "github": {"token": "", "api_base_url": "https://api.github.com"},
    "ai": {
        "enabled": False,
        "provider": "openai",  # openai, deepseek, etc.
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-3.5-turbo",
        "max_tokens": 2000,
        "temperature": 0.3,
        "use_proxy": False,  # AI是否使用代理
    },
    "notifications": {
        "qq": {"enabled": True, "default_groups": []},
        "email": {
            "enabled": False,
            "smtp_server": "",
            "smtp_port": 587,
            "username": "",
            "password": "",
            "recipients": [],
        },
    },
}


class ConfigManager:
    """配置管理器"""

    def __init__(self):
        self._config = None
        self._observer = None
        self._load_config()
        self._setup_file_watcher()

    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                # 合并默认配置
                self._config = self._merge_config(DEFAULT_CONFIG.copy(), config)
            else:
                self._config = DEFAULT_CONFIG.copy()
                self.save_config(self._config)
                logger.info("创建默认配置文件")
            return self._config
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            self._config = DEFAULT_CONFIG.copy()
            return self._config

    def _merge_config(self, default: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
        """合并配置, 确保所有默认键都存在"""
        for key, value in default.items():
            if key not in user:
                user[key] = value
            elif isinstance(value, dict) and isinstance(user[key], dict):
                user[key] = self._merge_config(value, user[key])
        return user

    def _setup_file_watcher(self):
        """配置文件监听器"""
        try:

            class ConfigHandler(FileSystemEventHandler):
                def __init__(self, config_manager):
                    self.config_manager = config_manager

                def on_modified(self, event):
                    if event.src_path == CONFIG_FILE:
                        logger.info("重新加载配置...")
                        self.config_manager._load_config()

            self._observer = Observer()
            self._observer.schedule(ConfigHandler(self), path=os.path.dirname(CONFIG_FILE), recursive=False)
            self._observer.start()
            # logger.debug("配置文件监听器已启动")
        except Exception as e:
            logger.warning(f"启动配置文件监听器失败: {e}")

    def get_config(self) -> Dict[str, Any]:
        """获取完整配置"""
        return self._config.copy() if self._config else DEFAULT_CONFIG.copy()

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        if not self._config:
            return default

        keys = key.split(".")
        value = self._config

        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def set(self, key: str, value: Any) -> bool:
        """设置配置项"""
        if not self._config:
            self._config = DEFAULT_CONFIG.copy()

        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
        return self.save_config(self._config)

    def save_config(self, config: Dict[str, Any]) -> bool:
        """保存配置文件"""
        lock_file = os.path.join(LOCK_DIR, "config.lock")
        temp_file = CONFIG_FILE + ".tmp"

        try:
            with FileLock(lock_file, timeout=10):
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=4, ensure_ascii=False)

                if os.path.exists(CONFIG_FILE):
                    os.remove(CONFIG_FILE)
                os.rename(temp_file, CONFIG_FILE)

                self._config = config
                logger.info("配置文件保存成功")
                return True
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
            return False

    def get_repo_config(self, repo_name: str) -> Optional[Dict[str, Any]]:
        """获取指定仓库的配置"""
        repo_mappings = self.get("repo_mappings", {})
        return repo_mappings.get(repo_name)

    def get_repo_secret(self, repo_name: str) -> str:
        """获取指定仓库的webhook密钥"""
        repo_config = self.get_repo_config(repo_name)
        if repo_config and repo_config.get("webhook_secret"):
            return repo_config["webhook_secret"]
        return ""

    def get_repo_groups(self, repo_name: str) -> list:
        """获取指定仓库的群组ID列表"""
        repo_config = self.get_repo_config(repo_name)
        if repo_config:
            return repo_config.get("qq_group_ids", repo_config.get("group_ids", []))
        return []

    def is_repo_enabled(self, repo_name: str) -> bool:
        """检查仓库是否启用"""
        repo_config = self.get_repo_config(repo_name)
        if repo_config:
            return repo_config.get("enabled", True)
        return False

    def get_user_qq(self, github_username: str) -> Optional[str]:
        """根据GitHub用户名获取QQ号"""
        user_mappings = self.get("user_mappings", {})
        return user_mappings.get(github_username)

    def get_github_token(self) -> str:
        """获取GitHub API Token"""
        return self.get("github.token", "")

    def get_ai_config(self) -> Dict[str, Any]:
        """获取AI配置"""
        return self.get("ai", {})

    def is_ai_enabled(self) -> bool:
        """检查AI功能是否启用"""
        return self.get("ai.enabled", False)

    def get_notification_config(self, channel: str) -> Dict[str, Any]:
        """获取通知渠道配置"""
        return self.get(f"notifications.{channel}", {})

    def get_repository_config(self, repo_name: str) -> Optional[Dict[str, Any]]:
        """获取仓库配置"""
        return self.get_repo_config(repo_name)

    def get_repo_allowed_message_types(self, repo_name: str) -> List[str]:
        """获取仓库允许的消息类型列表"""
        repo_config = self.get_repo_config(repo_name)
        if repo_config:
            return repo_config.get("allowed_message_types", [])
        return []

    def is_message_type_allowed(self, repo_name: str, message_type: str) -> bool:
        """检查指定仓库是否允许发送指定类型的消息"""
        allowed_types = self.get_repo_allowed_message_types(repo_name)
        # 如果没有配置allowed_message_types，默认允许所有类型
        if not allowed_types:
            return True
        return message_type in allowed_types

    def cleanup(self):
        """清理资源"""
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join()
                logger.info("配置文件监听器已停止")
            except Exception as e:
                logger.error(f"停止配置文件监听器失败: {e}")


# 全局配置管理器实例
_config_manager = None


def get_config_manager() -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_config() -> Dict[str, Any]:
    """获取配置的便捷函数"""
    return get_config_manager().get_config()


def cleanup_config():
    """清理配置管理器资源"""
    global _config_manager
    if _config_manager:
        _config_manager.cleanup()
        _config_manager = None
