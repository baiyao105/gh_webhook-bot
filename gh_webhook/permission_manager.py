"""
两层权限管理系统
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum

from loguru import logger


class QQPermissionLevel(Enum):
    """QQ层权限级别枚举"""
    NONE = "none"  # 允许使用无限制命令(例如 /og 命令)
    READ = "read"  # 允许使用AI功能, 并支持读取类型的MCP操作
    WRITE = "write"  # 允许完整使用 /webhook 命令和MCP工具
    SU = "su"  # 超级用户权限, 对应.env中的SUPERUSERS


class GitHubPermissionLevel(Enum):
    """GitHub层权限级别枚举"""
    NONE = "none"  # 允许使用AI聊天功能, 并支持读取类型的MCP操作
    WRITE = "write"  # 允许完整使用AI聊天功能和MCP工具


class SimplifiedPermissionManager:
    """简化的两层权限管理器"""

    def __init__(self, config_path: str = "permissions.json"):
        self.config_path = Path(config_path)
        self.permissions_data = {
            "qq_permissions": {},  # QQ用户权限 {qq_id: permission_level}
            "github_permissions": {},  # GitHub用户权限 {github_username: permission_level}
            "qq_github_mapping": {},  # QQ到GitHub的映射 {qq_id: github_username}
            "github_qq_mapping": {},  # GitHub到QQ的映射 {github_username: [qq_ids]}
            "last_updated": time.time(),
        }
        self._superusers = self._load_superusers_from_env()
        self._load_permissions()

    @property
    def superusers(self) -> List[str]:
        """获取超级用户列表"""
        return self._superusers

    def _load_superusers_from_env(self) -> List[str]:
        """从.env文件加载超级用户列表"""
        try:
            env_path = Path(__file__).parent.parent.parent.parent / ".env"
            if not env_path.exists():
                logger.warning(f".env文件不存在: {env_path}")
                return []

            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            for line in content.split("\n"):
                if line.strip().startswith("SUPERUSERS="):
                    superusers_str = line.split("=", 1)[1].strip()
                    import ast
                    superusers = ast.literal_eval(superusers_str)
                    logger.success(f"从.env加载超级用户: {superusers}")
                    return superusers

            logger.warning("未在.env文件中找到SUPERUSERS配置")
            return []
        except Exception as e:
            logger.error(f"加载超级用户配置失败: {e}")
            return []

    def _load_permissions(self):
        """加载权限配置"""
        try:
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.permissions_data.update(data)
            else:
                logger.info("权限配置文件不存在, 使用默认配置")
                self._save_permissions()
        except Exception as e:
            logger.error(f"加载权限配置失败: {e}")

    def _save_permissions(self):
        """保存权限配置"""
        try:
            self.permissions_data["last_updated"] = time.time()
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.permissions_data, f, ensure_ascii=False, indent=2)
            logger.debug("权限配置保存成功")
        except Exception as e:
            logger.error(f"保存权限配置失败: {e}")

    def is_superuser(self, qq_id: str) -> bool:
        """检查是否为超级用户"""
        return qq_id in self._superusers

    def get_qq_permission(self, qq_id: str) -> QQPermissionLevel:
        """获取QQ用户权限级别"""
        # 超级用户自动获得SU权限
        if self.is_superuser(qq_id):
            return QQPermissionLevel.SU
        permission_str = self.permissions_data["qq_permissions"].get(qq_id, "none")
        try:
            return QQPermissionLevel(permission_str)
        except ValueError:
            logger.warning(f"无效的QQ权限级别: {permission_str}, 使用默认权限")
            return QQPermissionLevel.NONE

    def set_qq_permission(self, qq_id: str, permission: QQPermissionLevel) -> bool:
        """设置QQ用户权限"""
        try:
            if permission == QQPermissionLevel.SU:
                return False

            self.permissions_data["qq_permissions"][qq_id] = permission.value
            self._save_permissions()
            logger.info(f"设置QQ用户 {qq_id} 权限为: {permission.value}")
            return True
        except Exception as e:
            logger.error(f"设置QQ权限失败: {e}")
            return False

    def remove_qq_permission(self, qq_id: str) -> bool:
        """移除QQ用户权限(恢复为NONE)"""
        try:
            if qq_id in self.permissions_data["qq_permissions"]:
                del self.permissions_data["qq_permissions"][qq_id]
                self._save_permissions()
                logger.info(f"移除QQ用户 {qq_id} 的权限")
            return True
        except Exception as e:
            logger.error(f"移除QQ权限失败: {e}")
            return False

    def _get_effective_qq_permission(self, qq_id: str) -> QQPermissionLevel:
        """获取有效的QQ权限(应用权限映射)"""
        base_permission = self.get_qq_permission(qq_id)
        if base_permission == QQPermissionLevel.NONE:
            github_username = self.get_github_by_qq(qq_id)
            if github_username:
                logger.debug(f"用户 {qq_id} 绑定了GitHub {github_username}, None权限映射为Read权限")
                return QQPermissionLevel.READ

        return base_permission

    def has_qq_permission(self, qq_id: str, required_permission: QQPermissionLevel) -> bool:
        """检查QQ用户是否有指定权限(应用权限映射)"""
        user_permission = self._get_effective_qq_permission(qq_id)
        permission_hierarchy = {
            QQPermissionLevel.NONE: 0,
            QQPermissionLevel.READ: 1,
            QQPermissionLevel.WRITE: 2,
            QQPermissionLevel.SU: 3,
        }

        user_level = permission_hierarchy.get(user_permission, 0)
        required_level = permission_hierarchy.get(required_permission, 0)

        return user_level >= required_level

    def get_github_permission(self, github_username: str) -> GitHubPermissionLevel:
        """获取GitHub用户权限级别"""
        permission_str = self.permissions_data["github_permissions"].get(github_username, "none")
        try:
            return GitHubPermissionLevel(permission_str)
        except ValueError:
            logger.warning(f"无效的GitHub权限级别: {permission_str}")
            return GitHubPermissionLevel.NONE

    def set_github_permission(self, github_username: str, permission: GitHubPermissionLevel) -> bool:
        """设置GitHub用户权限"""
        try:
            self.permissions_data["github_permissions"][github_username] = permission.value
            self._save_permissions()
            logger.info(f"设置GitHub用户 {github_username} 权限为: {permission.value}")
            return True
        except Exception as e:
            logger.error(f"设置GitHub权限失败: {e}")
            return False

    def remove_github_permission(self, github_username: str) -> bool:
        """移除GitHub用户权限"""
        try:
            if github_username in self.permissions_data["github_permissions"]:
                del self.permissions_data["github_permissions"][github_username]
                self._save_permissions()
                logger.info(f"移除GitHub用户 {github_username} 的权限")
            return True
        except Exception as e:
            logger.error(f"移除GitHub权限失败: {e}")
            return False

    def has_github_permission(self, github_username: str, required_permission: GitHubPermissionLevel) -> bool:
        """检查GitHub用户权限"""
        user_permission = self.get_github_permission(github_username)
        permission_hierarchy = {
            GitHubPermissionLevel.NONE: 0,
            GitHubPermissionLevel.WRITE: 1,
        }
        user_level = permission_hierarchy.get(user_permission, 0)
        required_level = permission_hierarchy.get(required_permission, 0)

        return user_level >= required_level

    def bind_qq_github(self, qq_id: str, github_username: str) -> bool:
        """绑定用户"""
        try:
            self.permissions_data["qq_github_mapping"][qq_id] = github_username
            if github_username not in self.permissions_data["github_qq_mapping"]:
                self.permissions_data["github_qq_mapping"][github_username] = []
            if qq_id not in self.permissions_data["github_qq_mapping"][github_username]:
                self.permissions_data["github_qq_mapping"][github_username].append(qq_id)
            self._save_permissions()
            logger.info(f"绑定用户: QQ {qq_id} <-> GitHub {github_username}")
            return True
        except Exception as e:
            logger.error(f"绑定用户失败: {e}")
            return False

    def unbind_qq_github(self, qq_id: str) -> bool:
        """解绑QQ用户和GitHub用户"""
        try:
            github_username = self.permissions_data["qq_github_mapping"].get(qq_id)
            if github_username:
                del self.permissions_data["qq_github_mapping"][qq_id]
                if github_username in self.permissions_data["github_qq_mapping"]:
                    qq_list = self.permissions_data["github_qq_mapping"][github_username]
                    if qq_id in qq_list:
                        qq_list.remove(qq_id)
                    if not qq_list:
                        del self.permissions_data["github_qq_mapping"][github_username]

                self._save_permissions()
                logger.info(f"解绑用户: QQ {qq_id} <-> GitHub {github_username}")
            return True
        except Exception as e:
            logger.error(f"解绑用户失败: {e}")
            return False

    def get_github_by_qq(self, qq_id: str) -> Optional[str]:
        """通过QQ号获取GitHub用户名"""
        return self.permissions_data["qq_github_mapping"].get(qq_id)

    def get_qq_by_github(self, github_username: str) -> List[str]:
        """通过GitHub用户名获取QQ号列表"""
        return self.permissions_data["github_qq_mapping"].get(github_username, [])

    def check_mcp_write_permission(self, qq_id: str, operation: str) -> bool:
        """检查MCP写入操作权限

        Args:
            qq_id: QQ用户ID
            operation: 操作类型(如：create_issue, close_issue, merge_pull_request等)

        Returns:
            是否有权限执行该操作
        """
        write_operations = {
            "create_issue",
            "update_issue",
            "close_issue",
            "create_pull_request",
            "update_pull_request",
            "merge_pull_request",
            "add_comment",
            "update_comment",
            "delete_comment",
            "create_label",
        }

        if operation not in write_operations:
            return True
        qq_permission = self._get_effective_qq_permission(qq_id)
        if qq_permission in [QQPermissionLevel.WRITE, QQPermissionLevel.SU]:
            return True
        github_username = self.get_github_by_qq(qq_id)
        if github_username:
            github_permission = self.get_github_permission(github_username)
            if github_permission == GitHubPermissionLevel.WRITE:
                return True

        return False

    def manage_qq_permission(self, operator_qq_id: str, target_qq_id: str, permission: QQPermissionLevel) -> bool:
        """管理QQ用户权限(仅SU)"""
        if not self.has_qq_permission(operator_qq_id, QQPermissionLevel.SU):
            logger.warning(f"用户 {operator_qq_id} 无权限管理其他用户权限")
            return False

        return self.set_qq_permission(target_qq_id, permission)

    def manage_github_permission(
        self,
        operator_qq_id: str,
        github_username: str,
        permission: GitHubPermissionLevel,
    ) -> bool:
        """设置GH用户权限(仅SU)"""
        if not self.has_qq_permission(operator_qq_id, QQPermissionLevel.SU):
            logger.warning(f"用户 {operator_qq_id} 无权限设置GitHub用户权限")
            return False

        return self.set_github_permission(github_username, permission)

    def manage_user_binding(
        self,
        operator_qq_id: str,
        qq_id: str,
        github_username: str,
        action: str = "bind",
    ) -> bool:
        """用户绑定(仅SU)"""
        if not self.has_qq_permission(operator_qq_id, QQPermissionLevel.SU):
            logger.warning(f"用户 {operator_qq_id} 无权限管理用户绑定")
            return False

        if action == "bind":
            return self.bind_qq_github(qq_id, github_username)
        elif action == "unbind":
            return self.unbind_qq_github(qq_id)
        else:
            logger.error(f"无效的操作: {action}")
            return False

    def get_user_info(self, qq_id: str) -> Dict[str, Any]:
        """获取用户完整信息"""
        qq_permission = self.get_qq_permission(qq_id)
        github_username = self.get_github_by_qq(qq_id)
        github_permission = None
        if github_username:
            github_permission = self.get_github_permission(github_username)
        effective_qq_permission = self._get_effective_qq_permission(qq_id)

        return {
            "qq_id": qq_id,
            "qq_permission": qq_permission.value,
            "effective_qq_permission": effective_qq_permission.value,
            "is_superuser": self.is_superuser(qq_id),
            "github_username": github_username,
            "github_permission": github_permission.value if github_permission else None,
        }

    def get_all_users(self) -> Dict[str, List[Dict[str, Any]]]:
        """获取所有用户信息(仅SU)"""
        qq_users = []
        github_users = []
        all_qq_ids = set(self.permissions_data["qq_permissions"].keys()) | set(self._superusers)
        for qq_id in all_qq_ids:
            qq_users.append(self.get_user_info(qq_id))
        for github_username, permission in self.permissions_data["github_permissions"].items():
            bound_qq_ids = self.get_qq_by_github(github_username)
            github_users.append(
                {
                    "github_username": github_username,
                    "github_permission": permission,
                    "bound_qq_ids": bound_qq_ids,
                }
            )

        return {"qq_users": qq_users, "github_users": github_users}

    def get_stats(self) -> Dict[str, Any]:
        """获取权限系统统计信息"""
        return {
            "total_qq_users": len(self.permissions_data["qq_permissions"]),
            "total_github_users": len(self.permissions_data["github_permissions"]),
            "total_superusers": len(self._superusers),
            "total_bindings": len(self.permissions_data["qq_github_mapping"]),
            "last_updated": self.permissions_data["last_updated"],
        }


_permission_manager = None


def get_permission_manager() -> SimplifiedPermissionManager:
    """获取全局权限管理实例"""
    global _permission_manager
    if _permission_manager is None:
        config_path = Path(__file__).parent / "permissions.json"
        _permission_manager = SimplifiedPermissionManager(str(config_path))
    return _permission_manager


# 我服了爸爸。
UnifiedPermissionManager = SimplifiedPermissionManager
PermissionLevel = QQPermissionLevel
CommandPermission = QQPermissionLevel
