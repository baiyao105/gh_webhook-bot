"""QQ消息监听
处理/gh命令相关功能
"""

import functools
from typing import Any, Dict, Optional

from loguru import logger

try:
    from nonebot import on_command, on_notice
    from nonebot.adapters.onebot.v11 import (
        Bot,
        MessageEvent,
        MessageSegment,
        Message,
        GroupRecallNoticeEvent,
        FriendRecallNoticeEvent,
    )
    from nonebot.params import CommandArg

    NONEBOT_AVAILABLE = True
except ImportError:
    NONEBOT_AVAILABLE = False
    logger.warning("NoneBot相关模块导入失败，QQ消息监听功能不可用")

from .permission_manager import (
    get_permission_manager,
    QQPermissionLevel,
    GitHubPermissionLevel,
)
from .ai_handler import get_unified_ai_handler
from . import get_bot


def handle_command_errors(func):
    """命令错误处理装饰器"""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            logger.error(f"命令执行出错: {e}")
            return self.formatter.error("系统错误", f"执行命令时发生错误: {str(e)}")
    return wrapper


class CommandValidator:
    """命令参数验证器"""

    @staticmethod
    def validate_qq_id(qq_id: str) -> tuple[bool, str]:
        """验证QQ号格式"""
        if not qq_id:
            return False, "请输入有效的QQ"
        if qq_id.startswith('[CQ:at,qq=') and qq_id.endswith(']'):
            try:
                actual_qq = qq_id[10:-1]  # 去掉[CQ:at,qq=和]
                if actual_qq.isdigit() and 5 <= len(actual_qq) <= 12:
                    return True, actual_qq  # 返回提取的QQ号
                else:
                    return False, "QQ号无效"
            except:
                return False, "格式解析失败"
        if not qq_id.isdigit():
            return False, "请输入有效的QQ号"
        
        if len(qq_id) < 5 or len(qq_id) > 12:
            return False, "QQ号长度应在5-12位之间"
        
        return True, qq_id

    @staticmethod
    def validate_github_username(username: str) -> tuple[bool, str]:
        """验证GitHub用户名格式"""
        if not username:
            return False, "请提供GitHub用户名"
        if len(username) > 39:
            return False, "GitHub用户名太长啦~"
        import re
        if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$', username):
            return False, "GitHub用户名格式不正确"
        return True, ""

    @staticmethod
    def validate_permissions(permissions: list[str]) -> tuple[bool, str, list[str]]:
        """验证权限列表"""
        valid_permissions = {
            "ai_chat": "AI对话权限",
            "github_read": "GitHub读取权限",
            "github_write": "GitHub写入权限",
            "user_manage": "用户管理权限",
            "system_admin": "系统管理权限"
        }

        invalid_perms = [p for p in permissions if p not in valid_permissions]
        if invalid_perms:
            return False, f"无效的权限: {', '.join(invalid_perms)}", []

        return True, "", permissions

    @staticmethod
    def validate_permission(permission: str) -> tuple[bool, str]:
        """验证单个权限"""
        valid_permissions = ["read", "write", "ai_chat", "mcp_tools"]
        if permission not in valid_permissions:
            return False, f"有效权限: {', '.join(valid_permissions)}"
        return True, ""

    @staticmethod
    def validate_github_username(username: str) -> tuple[bool, str]:
        """验证GitHub用户名格式"""
        if not username or len(username.strip()) == 0:
            return False, "GitHub用户名不能为空"

        username = username.strip()
        if len(username) > 39:
            return False, "GitHub用户名长度不能超过39个字符"
        import re
        if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$', username):
            return False, "GitHub用户名格式不正确"

        return True, ""

    @staticmethod
    def validate_list_type(list_type: str) -> tuple[bool, str]:
        """验证列表类型"""
        valid_types = ["all", "qq", "github"]
        if list_type not in valid_types:
            return False, f"无效的列表类型，支持: {', '.join(valid_types)}"
        return True, ""


class ResponseFormatter:
    """响应格式化器"""

    @staticmethod
    def success(message: str, details: str = "") -> str:
        """成功响应格式"""
        result = f"✅ {message}"
        if details:
            result += f"\n\n{details}"
        return result

    @staticmethod
    def error(message: str, details: str = "") -> str:
        """错误响应格式"""
        result = f"❌ {message}"
        if details:
            result += f"\n\n{details}"
        return result

    @staticmethod
    def info(title: str, content: str) -> str:
        """信息响应格式"""
        return f"📋 {title}\n\n{content}"

    @staticmethod
    def help(title: str, content: str) -> str:
        """帮助响应格式"""
        return f"🤖 {title}\n\n{content}"

    @staticmethod
    def format_user_info(user_info: dict) -> str:
        """格式化用户信息"""
        lines = [
            "👤 个人信息",
            "\n🔸 基本信息:",
            f"  QQ号: {user_info.get('qq_id', '未知')}",
            f"  GitHub: {user_info.get('github_username', '未绑定')}",
            f"  超级用户: {'是' if user_info.get('is_superuser') else '否'}"
        ]

        lines.append(f"\n🔸 QQ权限: {user_info.get('qq_permission', 'NONE')}")

        github_perm = user_info.get('github_permission')
        if github_perm and github_perm != 'NONE':
            lines.append(f"🔸 GitHub权限: {github_perm}")
        else:
            lines.append("🔸 GitHub权限: 无")

        return "\n".join(lines)

    @staticmethod
    def format_user_list(user_list: dict, list_type: str, stats: dict) -> str:
        """格式化用户列表"""
        lines = [f"📋 用户列表 ({list_type})"]
        if list_type in ["qq", "all"] and user_list.get("qq_users"):
            lines.append("\n🔸 QQ用户:")
            for user in user_list["qq_users"]:
                admin_mark = "👑" if user.get("is_superuser") else ""
                github_username = user.get("github_username", "未绑定")
                lines.append(f"  {admin_mark}QQ: {user['qq_id']} -> GitHub: {github_username}")
                lines.append(f"    QQ权限: {user['qq_permission']}")
                if user.get("github_permission"):
                    lines.append(f"    GitHub权限: {user['github_permission']}")
        if list_type in ["github", "all"] and user_list.get("github_users"):
            lines.append("\n🔸 GitHub用户:")
            for user in user_list["github_users"]:
                bound_qq_ids = user.get("bound_qq_ids", [])
                qq_list = ", ".join(bound_qq_ids) if bound_qq_ids else "未绑定"
                lines.append(f"  GitHub: {user['github_username']} -> QQ: {qq_list}")
                lines.append(f"    GitHub权限: {user['github_permission']}")
        if not user_list.get("qq_users") and not user_list.get("github_users"):
            lines.append("\n暂无用户数据")
        lines.extend([
            "\n统计信息:",
            f"QQ用户: {stats.get('total_qq_users', 0)}个",
            f"GitHub用户: {stats.get('total_github_users', 0)}个",
            f"用户绑定: {stats.get('total_bindings', 0)}个",
            f"超级用户: {stats.get('total_superusers', 0)}个"
        ])

        return "\n".join(lines)

    @staticmethod
    def format_github_user_list(github_users: list, stats: dict) -> str:
        """格式化GitHub用户列表"""
        lines = ["📋 GitHub用户绑定列表\n"]
        for i, user in enumerate(github_users[:10], 1):  # 限制显示前10个
            github_username = user.get("github_username", "未知")
            bound_qq_ids = user.get("bound_qq_ids", [])
            github_permission = user.get("github_permission", "NONE")
            lines.append(f"{i}.GitHub: {github_username}")
            lines.append(f"绑定QQ: {', '.join(bound_qq_ids) if bound_qq_ids else '无'}")
            lines.append(f"权限: {github_permission}")
            lines.append("")
        if len(github_users) > 10:
            lines.append(f"... 还有 {len(github_users) - 10} 个用户")
            lines.append("")
        lines.extend([
            "📊 统计信息:",
            f"GitHub用户: {stats.get('total_github_users', 0)}个",
            f"用户绑定: {stats.get('total_bindings', 0)}个"
        ])

        return "\n".join(lines)

    @staticmethod
    def format_command_help() -> str:
        """格式化命令帮助信息"""
        help_text = [
            "  /myinfo             - 查看个人信息",
            "",
            "💬 AI对话:",
            "  /gh <消息>",
            "",
        ]
            # "👥 用户管理命令 (仅超级用户):",
            # "  /adduser <QQ号> <权限>    - 添加用户",
            # "  /removeuser <QQ号>       - 移除用户",
            # "",
            # "🔗 GitHub权限管理 (仅超级用户):",
            # "  /ghperm bind <QQ号> <GitHub用户名>     - 绑定GitHub账户",
            # "  /ghperm unbind <QQ号>                 - 解绑GitHub账户",
            # "  /ghperm update <QQ号> <权限>          - 更新GitHub权限",
            # "  /ghperm info <QQ号>                   - 查看用户信息",
            # "  /ghperm list                          - 查看GitHub用户列表",
        return "\n".join(help_text)


class QQCommandHandler:
    """QQ命令处理器"""

    def __init__(self):
        self.permission_manager = get_permission_manager()
        self.webhook_bot = None
        self.config_manager = None
        self.validator = CommandValidator()
        self.formatter = ResponseFormatter()

    def get_webhook_bot(self):
        """获取webhook机器人实例"""
        if not self.webhook_bot:
            self.webhook_bot = get_bot()
        return self.webhook_bot

    async def handle_ai_chat(
        self,
        user_id: str,
        content: str,
        group_id: Optional[str] = None,
        reply_to: Optional[Dict[str, Any]] = None,
    ) -> str:
        """处理AI对话请求"""
        try:
            # 检查用户权限(使用新的简化权限系统)
            if not self.permission_manager.has_qq_permission(user_id, QQPermissionLevel.READ):
                return "你没有使用AI对话功能的权限\n请联系管理员申请权限~"

            # 获取配置管理器
            if not self.config_manager:
                webhook_bot = self.get_webhook_bot()
                if webhook_bot and hasattr(webhook_bot, "config_manager"):
                    self.config_manager = webhook_bot.config_manager
                else:
                    return "配置管理器不可用"

            # 获取AI处理器
            ai_handler = get_unified_ai_handler(self.config_manager)

            # 构建QQ消息上下文
            import time

            qq_context = {
                "platform": "qq",
                "user_id": user_id,
                "group_id": group_id,
                "message_id": f"qq_{int(time.time() * 1000)}",  # 生成消息ID
                "content": content,
                "timestamp": time.time(),
                "reply_to": reply_to,
            }

            # 调用AI处理器的QQ消息处理方法
            response = await ai_handler.handle_qq_message(qq_context)

            return response

        except Exception as e:
            logger.error(f"处理AI对话异常: {e}")
            return f"处理对话时出现错误\n错误信息: {str(e)}"

    async def handle_message_recall(
        self, recalled_message_id: int, operator_id: int, group_id: Optional[int] = None
    ) -> bool:
        """处理消息撤回事件"""
        try:
            # 获取配置管理器和AI处理器
            if not self.config_manager:
                webhook_bot = self.get_webhook_bot()
                if webhook_bot and hasattr(webhook_bot, "config_manager"):
                    self.config_manager = webhook_bot.config_manager
                else:
                    logger.error("配置管理器不可用，无法处理消息撤回")
                    return False

            ai_handler = get_unified_ai_handler(self.config_manager)

            # 调用AI处理器的消息撤回处理方法
            success = await ai_handler.handle_qq_message_recall(recalled_message_id, operator_id, group_id)

            if success:
                logger.success(f"消息撤回处理成功: 消息ID {recalled_message_id}")
            else:
                logger.warning(f"消息撤回处理失败: 消息ID {recalled_message_id}")

            return success

        except Exception as e:
            logger.error(f"处理消息撤回异常: {e}")
            return False

    @handle_command_errors
    async def handle_github_operation(self, bot: Bot, event: MessageEvent, target: str, operation: str) -> str:
        """处理GitHub操作请求

        Args:
            bot: Bot实例
            event: 消息事件
            target: 目标 (PR/Issue ID)
            operation: 操作命令

        Returns:
            操作结果
        """
        try:
            webhook_bot = self.get_webhook_bot()
            if not webhook_bot or not webhook_bot.initialized:
                return "GitHub服务未初始化"

            # 检查MCP工具是否可用
            if not hasattr(webhook_bot, "unified_ai_handler") or not webhook_bot.unified_ai_handler:
                return "GitHub工具不可用"

            ai_handler = webhook_bot.unified_ai_handler
            if not ai_handler._is_mcp_tools_initialized():
                return "GitHub工具未就绪"

            # 解析目标ID
            if not target.isdigit():
                return "请提供有效的PR/Issue编号"

            target_id = int(target)

            # 这里需要根据operation执行相应的GitHub操作
            # TODO: 实现具体的GitHub操作逻辑
            supported_operations = ["clone", "open", "merge", "close", "review", "info"]

            if operation not in supported_operations:
                return f"不支持的操作: {operation}\n支持的操作: {', '.join(supported_operations)}"

            # 示例响应
            response = f"正在执行GitHub操作...\n\n目标: #{target_id}\n操作: {operation}\n\n这是一个示例响应，实际的GitHub操作逻辑需要进一步实现 ✨"

            return response

        except Exception as e:
            logger.error(f"GitHub操作处理异常: {e}")
            return f"执行GitHub操作时出现错误: {str(e)}"

    @handle_command_errors
    async def handle_userlist(self, bot: Bot, event: MessageEvent, list_type: str = "all") -> str:
        """处理用户列表查询

        Args:
            bot: Bot实例
            event: 消息事件
            list_type: 列表类型 (qq/github/all)

        Returns:
            用户列表信息
        """
        try:
            is_valid, error_msg = self.validator.validate_list_type(list_type)
            if not is_valid:
                return self.formatter.error("参数错误", error_msg)
            user_list = self.permission_manager.get_all_users()
            stats = self.permission_manager.get_stats()
            return self.formatter.format_user_list(user_list, list_type, stats)

        except Exception as e:
            logger.error(f"获取用户列表异常: {e}")
            return self.formatter.error("获取用户列表失败", f"错误信息: {str(e)}")


    @handle_command_errors
    async def handle_myinfo(self, bot: Bot, event: MessageEvent) -> str:
        """处理个人信息查询

        Args:
            bot: Bot实例
            event: 消息事件

        Returns:
            个人信息
        """
        try:
            qq_id = str(event.user_id)
            user_info = self.permission_manager.get_user_info(qq_id)

            if not user_info or user_info["qq_permission"] == "NONE":
                return self.formatter.error("用户未注册", f"你还没有相关权限哦~ 请联系管理员添加权限\n\nQQ号: {qq_id}")
            return self.formatter.format_user_info(user_info)

        except Exception as e:
            logger.error(f"获取个人信息异常: {e}")
            return self.formatter.error("获取个人信息失败", f"错误信息: {str(e)}")


# 创建命令处理器实例
command_handler = QQCommandHandler()


if NONEBOT_AVAILABLE:
    # 注册/gh命令
    gh_command = on_command("gh", priority=5, block=True)

    @gh_command.handle()
    async def handle_gh_command(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
        """处理/gh命令"""
        try:
            qq_id = str(event.user_id)

            # 解析命令参数
            args_text = args.extract_plain_text().strip()

            if not args_text:
                # 无参数，显示帮助信息
                help_text = """📝 基本用法:
  /gh <内容>  - AI对话
  /gh userlist [类型]  - 查看用户列表
  /gh myinfo  - 查看个人信息"""

                reply_msg = MessageSegment.reply(event.message_id)
                await gh_command.send(reply_msg + help_text)
                return

            # 解析参数
            parts = args_text.split()

            # 检查是否为特殊命令
            if parts[0] == "userlist":
                # 检查权限
                if not command_handler.permission_manager.has_qq_permission(qq_id, QQPermissionLevel.SU):
                    reply_msg = MessageSegment.reply(event.message_id)
                    await gh_command.send(reply_msg + "你没有查看用户列表的权限")
                    return

                list_type = parts[1] if len(parts) > 1 else "all"
                response = await command_handler.handle_userlist(bot, event, list_type)

            elif parts[0] == "myinfo":
                response = await command_handler.handle_myinfo(bot, event)

            elif parts[0] == "help":
                response = command_handler.formatter.format_command_help()

            elif parts[0].isdigit() and len(parts) > 1:
                # GitHub操作命令
                if not command_handler.permission_manager.has_qq_permission(qq_id, QQPermissionLevel.READ):
                    reply_msg = MessageSegment.reply(event.message_id)
                    await gh_command.send(reply_msg + "你没有GitHub操作权限")
                    return

                target_id = parts[0]
                operation = parts[1]
                response = await command_handler.handle_github_operation(bot, event, target_id, operation)

            else:
                # AI对话
                if not command_handler.permission_manager.has_qq_permission(qq_id, QQPermissionLevel.READ):
                    reply_msg = MessageSegment.reply(event.message_id)
                    await gh_command.send(reply_msg + "你没有AI权限")
                    return

                # 获取引用消息信息
                reply_to = None
                for segment in event.message:
                    if segment.type == "reply":
                        try:
                            reply_msg_id = segment.data.get("id")
                            if reply_msg_id:
                                reply_msg = await bot.get_msg(message_id=int(reply_msg_id))
                                reply_to = {
                                    "message_id": reply_msg_id,
                                    "content": reply_msg.get("message", ""),
                                    "sender": reply_msg.get("sender", {}),
                                }
                        except Exception as e:
                            logger.debug(f"获取引用消息失败: {e}")

                # 调用AI对话处理
                response = await command_handler.handle_ai_chat(
                    user_id=qq_id,
                    content=args_text,
                    group_id=getattr(event, "group_id", None),
                    reply_to=reply_to,
                )

            # 发送回复
            reply_msg = MessageSegment.reply(event.message_id)
            sent_message = await gh_command.send(reply_msg + response)
            if sent_message and hasattr(sent_message, 'message_id'):
                try:
                    ai_handler = command_handler.ai_handler
                    if ai_handler and ai_handler.context_manager:
                        from .ai_models import ContextType
                        context_type = ContextType.QQ_GROUP if getattr(event, "group_id", None) else ContextType.QQ_PRIVATE
                        context_id = ai_handler._generate_context_id(
                            context_type,
                            group_id=str(getattr(event, "group_id", None)) if getattr(event, "group_id", None) else None,
                            user_id=str(qq_id),
                        )
                        conv_context = ai_handler.context_manager.get_context(context_id)
                        if conv_context and conv_context.messages:
                            last_message = conv_context.messages[-1]
                            if last_message.role == "assistant":
                                if not last_message.metadata:
                                    last_message.metadata = {}
                                last_message.metadata["message_id"] = str(sent_message.message_id)
                                ai_handler.context_manager.save_context(conv_context)
                except Exception as e:
                    logger.warning(f"保存回复消息ID失败: {e}")

        except Exception as e:
            logger.error(f"处理/gh命令异常: {e}")
            reply_msg = MessageSegment.reply(event.message_id)
            await gh_command.send(reply_msg + f"命令处理出错: {str(e)}")

    # 管理员命令 - 添加用户
    add_user_command = on_command("adduser", priority=5, block=True)

    @add_user_command.handle()
    async def handle_add_user(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
        """添加用户命令"""
        try:
            qq_id = str(event.user_id)

            # 检查管理员权限
            if not command_handler.permission_manager.has_qq_permission(qq_id, QQPermissionLevel.SU):
                reply_msg = MessageSegment.reply(event.message_id)
                await add_user_command.send(reply_msg + "你没有添加用户的权限")
                return

            args_text = args.extract_plain_text().strip()
            parts = args_text.split()

            if len(parts) < 2:
                help_text = """👥 添加用户命令

用法: /adduser <QQ号> <GitHub用户名> [权限...]

可用权限:
  ai_chat - AI对话权限
  github_read - GitHub读取权限
  github_write - GitHub写入权限
  user_manage - 用户管理权限
  system_admin - 系统管理权限

示例:
  /adduser 123456789 username ai_chat github_read"""

                reply_msg = MessageSegment.reply(event.message_id)
                await add_user_command.send(reply_msg + help_text)
                return

            target_qq = parts[0]
            github_username = parts[1]
            permissions = parts[2:] if len(parts) > 2 else ["ai_chat", "github_read"]

            # 验证QQ号格式
            is_valid_qq, qq_result = command_handler.validator.validate_qq_id(target_qq)
            if not is_valid_qq:
                reply_msg = MessageSegment.reply(event.message_id)
                await add_user_command.send(reply_msg + qq_result)
                return
            target_qq = qq_result

            # 添加用户 - 使用新权限系统
            try:
                # 绑定QQ和GitHub
                bind_success = command_handler.permission_manager.manage_user_binding(
                    qq_id, target_qq, github_username, "bind"
                )

                # 设置QQ权限(默认READ)
                qq_perm = QQPermissionLevel.READ
                if "github_write" in permissions or "ai_chat" in permissions:
                    qq_perm = QQPermissionLevel.WRITE

                perm_success = command_handler.permission_manager.manage_qq_permission(qq_id, target_qq, qq_perm)

                # 如果有GitHub写权限，设置GitHub权限
                github_success = True
                if "github_write" in permissions:
                    github_success = command_handler.permission_manager.manage_github_permission(
                        qq_id, github_username, GitHubPermissionLevel.WRITE
                    )

                if bind_success and perm_success and github_success:
                    response = f"✅ 用户添加成功!\n\nQQ: {target_qq}\nGitHub: {github_username}\n权限: {qq_perm.value}"
                    if "github_write" in permissions:
                        response += "\nGitHub权限: WRITE"
                else:
                    response = "❌ 用户添加失败，请检查参数或查看日志"
            except Exception as e:
                logger.error(f"添加用户失败: {e}")
                response = f"❌ 用户添加失败: {str(e)}"

            reply_msg = MessageSegment.reply(event.message_id)
            await add_user_command.send(reply_msg + response)

        except Exception as e:
            logger.error(f"添加用户命令异常: {e}")
            reply_msg = MessageSegment.reply(event.message_id)
            await add_user_command.send(reply_msg + f"添加用户时出错: {str(e)}")

    # 管理员命令 - 移除用户
    remove_user_command = on_command("removeuser", priority=5, block=True)

    @remove_user_command.handle()
    async def handle_remove_user(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
        """移除用户命令"""
        try:
            qq_id = str(event.user_id)

            # 检查管理员权限
            if not command_handler.permission_manager.has_qq_permission(qq_id, QQPermissionLevel.SU):
                reply_msg = MessageSegment.reply(event.message_id)
                await remove_user_command.send(reply_msg + command_handler.formatter.error("权限不足", "只有超级用户可以移除用户"))
                return

            args_text = args.extract_plain_text().strip()

            if not args_text:
                help_text = command_handler.formatter.help(
                    "移除用户命令",
                    "用法: /removeuser <QQ号>\n\n示例:\n  /removeuser 123456789"
                )
                reply_msg = MessageSegment.reply(event.message_id)
                await remove_user_command.send(reply_msg + help_text)
                return

            target_qq = args_text

            is_valid_qq, qq_result = command_handler.validator.validate_qq_id(target_qq)
            if not is_valid_qq:
                reply_msg = MessageSegment.reply(event.message_id)
                await remove_user_command.send(reply_msg + command_handler.formatter.error("QQ号格式错误", qq_result))
                return
            target_qq = qq_result

            # 获取用户信息 - 使用新权限系统
            user_info = command_handler.permission_manager.get_user_info(target_qq)
            if not user_info or user_info["qq_permission"] == "NONE":
                reply_msg = MessageSegment.reply(event.message_id)
                await remove_user_command.send(reply_msg + command_handler.formatter.error("用户不存在", f"用户 {target_qq} 不存在或未注册"))
                return

            # 保存GitHub用户名(在删除前)
            github_username = user_info.get("github_username", "未知")

            # 移除用户 - 使用新权限系统
            try:
                # 解绑QQ和GitHub
                unbind_success = True
                if github_username and github_username != "未知":
                    unbind_success = command_handler.permission_manager.manage_user_binding(
                        qq_id, target_qq, github_username, "unbind"
                    )

                # 移除QQ权限
                perm_success = command_handler.permission_manager.manage_qq_permission(
                    qq_id, target_qq, QQPermissionLevel.NONE
                )

                if unbind_success and perm_success:
                    response = command_handler.formatter.success(
                        "用户移除成功",
                        f"QQ: {target_qq}\nGitHub: {github_username}\n\n用户已被成功移除 ✨"
                    )
                else:
                    response = command_handler.formatter.error("移除失败", "操作未完全成功")
            except Exception as e:
                logger.error(f"移除用户失败: {e}")
                response = command_handler.formatter.error("移除用户失败", f"错误信息: {str(e)}")

            reply_msg = MessageSegment.reply(event.message_id)
            await remove_user_command.send(reply_msg + response)

        except Exception as e:
            logger.error(f"移除用户命令异常: {e}")
            reply_msg = MessageSegment.reply(event.message_id)
            await remove_user_command.send(reply_msg + command_handler.formatter.error("命令执行失败", f"错误信息: {str(e)}"))

    # GitHub权限管理命令
    github_perm_command = on_command("ghperm", priority=5, block=True)

    @github_perm_command.handle()
    async def handle_github_perm(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
        """GitHub权限管理命令"""
        try:
            user_id = str(event.user_id)

            # 检查管理员权限
            if not command_handler.permission_manager.has_qq_permission(user_id, QQPermissionLevel.SU):
                reply_msg = MessageSegment.reply(event.message_id)
                await github_perm_command.send(reply_msg + "❌ 权限不足，仅管理员可使用此命令")
                return

            args_text = args.extract_plain_text().strip()
            if not args_text:
                help_text = (
                    "🔗 绑定QQ到GitHub账户:\n"
                    "/ghperm bind <QQ号> <GitHub用户名>\n\n"
                    "🔓 解绑QQ:\n"
                    "/ghperm unbind <QQ号>\n\n"
                    "⚙️ 更新GitHub权限:\n"
                    "/ghperm update <GitHub用户名> <权限列表>\n"
                    "权限: ai_chat,github_read,github_write,mcp_tools\n\n"
                    "📊 查看GitHub用户信息:\n"
                    "/ghperm info <GitHub用户名>\n\n"
                    "📋 列出所有绑定:\n"
                    "/ghperm list"
                )
                reply_msg = MessageSegment.reply(event.message_id)
                await github_perm_command.send(reply_msg + help_text)
                return

            parts = args_text.split()
            if len(parts) < 1:
                reply_msg = MessageSegment.reply(event.message_id)
                await github_perm_command.send(reply_msg + "❌ 参数不足")
                return

            action = parts[0].lower()

            if action == "bind":
                if len(parts) != 3:
                    help_text = command_handler.formatter.help(
                        "参数不足",
                        "用法: /ghperm bind <QQ号> <GitHub用户名>\n\n示例:\n  /ghperm bind 123456789 octocat"
                    )
                    reply_msg = MessageSegment.reply(event.message_id)
                    await github_perm_command.send(reply_msg + help_text)
                    return

                qq_id, github_username = parts[1], parts[2]

                is_valid_qq, qq_result = command_handler.validator.validate_qq_id(qq_id)
                if not is_valid_qq:
                    reply_msg = MessageSegment.reply(event.message_id)
                    await github_perm_command.send(reply_msg + command_handler.formatter.error("QQ号格式错误", qq_result))
                    return
                qq_id = qq_result
                is_valid_github, github_error = command_handler.validator.validate_github_username(github_username)
                if not is_valid_github:
                    reply_msg = MessageSegment.reply(event.message_id)
                    await github_perm_command.send(reply_msg + command_handler.formatter.error("GitHub用户名格式错误", github_error))
                    return

                try:
                    # 绑定QQ和GitHub
                    bind_success = command_handler.permission_manager.manage_user_binding(
                        user_id, qq_id, github_username, "bind"
                    )
                    perm_success = command_handler.permission_manager.manage_qq_permission(
                        user_id, qq_id, QQPermissionLevel.READ
                    )

                    if bind_success and perm_success:
                        response = command_handler.formatter.success(
                            "绑定成功",
                            f"QQ: {qq_id}\nGitHub: {github_username}\n权限: READ\n\n账户绑定完成 ✨"
                        )
                    else:
                        response = command_handler.formatter.error("绑定失败", "请检查参数或用户是否已存在")
                except Exception as e:
                    logger.error(f"绑定失败: {e}")
                    response = command_handler.formatter.error("绑定失败", f"错误信息: {str(e)}")

                reply_msg = MessageSegment.reply(event.message_id)
                await github_perm_command.send(reply_msg + response)

            elif action == "unbind":
                if len(parts) != 2:
                    help_text = command_handler.formatter.help(
                        "参数不足",
                        "用法: /ghperm unbind <QQ号>\n\n示例:\n  /ghperm unbind 123456789"
                    )
                    reply_msg = MessageSegment.reply(event.message_id)
                    await github_perm_command.send(reply_msg + help_text)
                    return

                qq_id = parts[1]

                # 验证QQ号格式
                is_valid_qq, qq_result = command_handler.validator.validate_qq_id(qq_id)
                if not is_valid_qq:
                    reply_msg = MessageSegment.reply(event.message_id)
                    await github_perm_command.send(reply_msg + command_handler.formatter.error("QQ号格式错误", qq_result))
                    return
                qq_id = qq_result  # 使用提取或验证后的QQ号

                user_info = command_handler.permission_manager.get_user_info(qq_id)
                if not user_info or user_info["qq_permission"] == "NONE":
                    reply_msg = MessageSegment.reply(event.message_id)
                    await github_perm_command.send(reply_msg + command_handler.formatter.error("用户不存在", f"用户 {qq_id} 不存在或未注册"))
                    return

                # 保存GitHub用户名(在删除前)
                github_username = user_info.get("github_username", "未知")

                # 使用新权限系统进行解绑
                try:
                    # 解绑QQ和GitHub
                    unbind_success = True
                    if github_username and github_username != "未知":
                        unbind_success = command_handler.permission_manager.manage_user_binding(
                            user_id, qq_id, github_username, "unbind"
                        )

                    # 移除QQ权限
                    perm_success = command_handler.permission_manager.manage_qq_permission(
                        user_id, qq_id, QQPermissionLevel.NONE
                    )

                    if unbind_success and perm_success:
                        response = command_handler.formatter.success(
                            "解绑成功",
                            f"QQ: {qq_id}\nGitHub: {github_username}\n\n账户解绑完成 ✨"
                        )
                    else:
                        response = command_handler.formatter.error("解绑失败", "操作未完全成功，请检查日志")
                except Exception as e:
                    logger.error(f"解绑失败: {e}")
                    response = command_handler.formatter.error("解绑失败", f"错误信息: {str(e)}")

                reply_msg = MessageSegment.reply(event.message_id)
                await github_perm_command.send(reply_msg + response)

            elif action == "update":
                if len(parts) < 3:
                    help_text = command_handler.formatter.help(
                        "参数不足",
                        "用法: /ghperm update <GitHub用户名> <权限>\n权限: read/write\n\n示例:\n  /ghperm update octocat write"
                    )
                    reply_msg = MessageSegment.reply(event.message_id)
                    await github_perm_command.send(reply_msg + help_text)
                    return

                github_username = parts[1]
                permission = parts[2] if len(parts) > 2 else "read"

                # 验证GitHub用户名格式
                is_valid_github, github_error = command_handler.validator.validate_github_username(github_username)
                if not is_valid_github:
                    reply_msg = MessageSegment.reply(event.message_id)
                    await github_perm_command.send(reply_msg + command_handler.formatter.error("GitHub用户名格式错误", github_error))
                    return

                valid_permissions = ["read", "write"]
                if permission not in valid_permissions:
                    reply_msg = MessageSegment.reply(event.message_id)
                    await github_perm_command.send(
                        reply_msg + command_handler.formatter.error(
                            "权限格式错误",
                            f"有效权限: {', '.join(valid_permissions)}"
                        )
                    )
                    return

                # 使用新权限系统更新GitHub权限
                try:
                    # 映射权限
                    github_perm = GitHubPermissionLevel.READ if permission == "read" else GitHubPermissionLevel.WRITE

                    success = command_handler.permission_manager.manage_github_permission(
                        user_id, github_username, github_perm
                    )

                    if success:
                        # 获取绑定的QQ号列表
                        qq_ids = command_handler.permission_manager.get_qq_by_github(github_username) or []
                        qq_list = ", ".join(qq_ids) if qq_ids else "无"
                        response = command_handler.formatter.success(
                            "权限更新成功",
                            f"GitHub: {github_username}\n绑定QQ: {qq_list}\n新权限: {github_perm.value}\n\n权限已更新 ✨"
                        )
                    else:
                        response = command_handler.formatter.error("更新失败", f"GitHub用户 {github_username} 不存在或操作失败")
                except Exception as e:
                    logger.error(f"更新GitHub权限失败: {e}")
                    response = command_handler.formatter.error("更新失败", f"错误信息: {str(e)}")

                reply_msg = MessageSegment.reply(event.message_id)
                await github_perm_command.send(reply_msg + response)

            elif action == "info":
                if len(parts) != 2:
                    help_text = command_handler.formatter.help(
                        "参数不足",
                        "用法: /ghperm info <GitHub用户名>\n\n示例:\n  /ghperm info octocat"
                    )
                    reply_msg = MessageSegment.reply(event.message_id)
                    await github_perm_command.send(reply_msg + help_text)
                    return

                github_username = parts[1]

                # 验证GitHub用户名格式
                is_valid_github, github_error = command_handler.validator.validate_github_username(github_username)
                if not is_valid_github:
                    reply_msg = MessageSegment.reply(event.message_id)
                    await github_perm_command.send(reply_msg + command_handler.formatter.error("GitHub用户名格式错误", github_error))
                    return

                # 使用新权限系统获取GitHub用户信息
                try:
                    github_permission = command_handler.permission_manager.get_github_permission(github_username)
                    if github_permission == GitHubPermissionLevel.NONE:
                        reply_msg = MessageSegment.reply(event.message_id)
                        await github_perm_command.send(reply_msg + command_handler.formatter.error("用户不存在", f"GitHub用户 {github_username} 不存在或未注册"))
                        return

                    qq_ids = command_handler.permission_manager.get_qq_by_github(github_username) or []

                    response = command_handler.formatter.info(
                        "GitHub用户信息",
                        f"GitHub: {github_username}\n绑定QQ: {', '.join(qq_ids) if qq_ids else '无'}\n权限: {github_permission.value}\n\n用户信息查询完成 ✨"
                    )
                except Exception as e:
                    logger.error(f"获取GitHub用户信息失败: {e}")
                    reply_msg = MessageSegment.reply(event.message_id)
                    await github_perm_command.send(reply_msg + command_handler.formatter.error("获取信息失败", f"错误信息: {str(e)}"))
                    return

                reply_msg = MessageSegment.reply(event.message_id)
                await github_perm_command.send(reply_msg + response)

            elif action == "list":
                # 使用新权限系统获取所有用户信息
                try:
                    all_users = command_handler.permission_manager.get_all_users()
                    github_users = all_users.get("github_users", [])
                    stats = command_handler.permission_manager.get_stats()

                    if not github_users:
                        reply_msg = MessageSegment.reply(event.message_id)
                        await github_perm_command.send(reply_msg + command_handler.formatter.info("GitHub用户列表", "暂无GitHub用户绑定"))
                        return
                except Exception as e:
                    logger.error(f"获取用户列表失败: {e}")
                    reply_msg = MessageSegment.reply(event.message_id)
                    await github_perm_command.send(reply_msg + command_handler.formatter.error("获取列表失败", f"错误信息: {str(e)}"))
                    return

                response_lines = ["📋 GitHub用户绑定列表\n"]

                for i, user in enumerate(github_users[:10], 1):  # 限制显示前10个
                    github_username = user.get("github_username", "未知")
                    bound_qq_ids = user.get("bound_qq_ids", [])
                    github_permission = user.get("github_permission", "NONE")

                    response_lines.append(f"{i}. GitHub: {github_username}")
                    response_lines.append(f"   绑定QQ: {', '.join(bound_qq_ids) if bound_qq_ids else '无'}")
                    response_lines.append(f"   权限: {github_permission}")
                    response_lines.append("")

                if len(github_users) > 10:
                    response_lines.append(f"... 还有 {len(github_users) - 10} 个用户")
                    response_lines.append("")
                response_lines.extend([
                    "📊 统计信息:",
                    f"  GitHub用户: {stats.get('total_github_users', 0)}个",
                    f"  用户绑定: {stats.get('total_bindings', 0)}个"
                ])

                response = "\n".join(response_lines)
                reply_msg = MessageSegment.reply(event.message_id)
                await github_perm_command.send(reply_msg + response)

            else:
                reply_msg = MessageSegment.reply(event.message_id)
                await github_perm_command.send(reply_msg + f"❌ 未知操作: {action}\n\n使用 /ghperm 查看帮助")

        except Exception as e:
            logger.error(f"GitHub权限管理命令异常: {e}")
            reply_msg = MessageSegment.reply(event.message_id)
            await github_perm_command.send(reply_msg + f"❌ 命令执行出错: {str(e)}")

    # 消息撤回事件监听器
    group_recall_notice = on_notice()
    friend_recall_notice = on_notice()

    @group_recall_notice.handle()
    async def handle_group_recall(bot: Bot, event: GroupRecallNoticeEvent):
        """处理群消息撤回事件"""
        try:
            logger.debug(f"检测到群消息撤回: 群{event.group_id}, 消息ID {event.message_id}, 操作者 {event.operator_id}")

            # 调用命令处理器的消息撤回处理方法
            success = await command_handler.handle_message_recall(
                recalled_message_id=event.message_id,
                operator_id=event.operator_id,
                group_id=event.group_id,
            )

            if not success:
                logger.warning(f"群消息撤回处理失败: 群{event.group_id}, 消息ID {event.message_id}")

        except Exception as e:
            logger.error(f"处理群消息撤回异常: {e}")

    @friend_recall_notice.handle()
    async def handle_friend_recall(bot: Bot, event: FriendRecallNoticeEvent):
        """处理好友消息撤回事件"""
        try:
            logger.debug(f"检测到好友消息撤回: 用户{event.user_id}, 消息ID {event.message_id}")

            # 调用命令处理器的消息撤回处理方法
            success = await command_handler.handle_message_recall(
                recalled_message_id=event.message_id,
                operator_id=event.user_id,
                group_id=None,  # 私聊没有群ID
            )

            if not success:
                logger.warning(f"好友消息撤回处理失败: 用户{event.user_id}, 消息ID {event.message_id}")

        except Exception as e:
            logger.error(f"处理好友消息撤回异常: {e}")

else:
    logger.warning("NoneBot不可用，QQ命令监听器未注册")


__all__ = ["QQCommandHandler", "command_handler"]
