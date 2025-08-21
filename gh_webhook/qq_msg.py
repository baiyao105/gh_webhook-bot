"""
QQ消息处理子模块
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

from loguru import logger

try:
    from nonebot import get_bot
    from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment
    from nonebot.exception import ActionFailed, NetworkError

    NONEBOT_AVAILABLE = True
except ImportError:
    NONEBOT_AVAILABLE = False
    Bot = None
    Message = None
    MessageSegment = None


class QQMessageSender:
    """QQ消息发送"""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.bot_instance = None
        self.user_mappings = {}
        self.rate_limiter = {}
        self._load_user_mappings()  # 用户映射

    def _load_user_mappings(self):
        """加载用户映射配置"""
        try:
            mappings = self.config_manager.get("user_mappings", {})
            self.user_mappings = mappings
            logger.info(f"加载用户映射: {len(self.user_mappings)} 个映射")
        except Exception as e:
            logger.error(f"加载用户映射失败: {e}")
            self.user_mappings = {}

    def _get_bot_instance(self) -> Optional[Bot]:
        """获取机器人实例"""
        if not NONEBOT_AVAILABLE:
            logger.error("NB爆炸了(嗯对???")
            return None

        try:
            if self.bot_instance is None:
                bot = get_bot()
                self.bot_instance = bot
                logger.info(f"获取到机器人实例: {bot.self_id}")

            return self.bot_instance
        except Exception as e:
            logger.error(f"获取机器人实例失败: {e}")
            return None

    def _check_rate_limit(self, group_id: str) -> bool:
        """检查发送频率限制"""
        current_time = time.time()
        # 每个群每分钟最多15条消息
        if group_id not in self.rate_limiter:
            self.rate_limiter[group_id] = []
        self.rate_limiter[group_id] = [
            timestamp for timestamp in self.rate_limiter[group_id] if current_time - timestamp < 60
        ]

        if len(self.rate_limiter[group_id]) >= 15:
            logger.warning(f"群 {group_id} 发送频率超限, 跳过消息")
            return False

        self.rate_limiter[group_id].append(current_time)  # 记录当前发送时间
        return True

    def _format_github_username(self, username: str) -> str:
        """格式化GitHub用户名为QQ@提及"""
        if not username:
            return username
        qq_number = self.user_mappings.get(username)
        if qq_number:
            return f"@{qq_number}"
        return username

    def _process_message_content(self, content: str) -> str:
        """处理消息内容, 转换GitHub用户名为QQ@提及"""
        # TODO: 更复杂的用户名转换逻辑
        processed_content = content
        for github_username, qq_number in self.user_mappings.items():
            patterns = [
                f"@{github_username}",
                f"用户: {github_username}",
                f"作者: {github_username}",
                f"推送者: {github_username}",
                f"发布者: {github_username}",
                f"创建者: {github_username}",
                f"删除者: {github_username}",
                f"合并者: {github_username}",
                f"触发者: {github_username}",
            ]
            for pattern in patterns:
                if pattern in processed_content:
                    replacement = pattern.replace(github_username, f"@{qq_number}")
                    processed_content = processed_content.replace(pattern, replacement)
        return processed_content

    def _create_message_segments(self, content, target_config: Dict[str, Any]) -> List:
        """创建消息段"""
        if not NONEBOT_AVAILABLE:
            return []
        segments = []
        processed_content = self._process_message_content(content.content)
        # 标题(如果有)
        if content.title and content.title != content.content:
            segments.append(MessageSegment.text(f"📢 {content.title}\n\n"))
        # 主要内容
        segments.append(MessageSegment.text(processed_content))
        # 检查内容中是否已经包含链接，避免重复显示
        content_has_link = "🔗" in processed_content and content.url and content.url in processed_content
        # 链接(如果有且内容中没有包含)
        if content.url and not content_has_link:
            segments.append(MessageSegment.text(f"\n\n🔗 链接: {content.url}"))
        # 图片(如果有且配置允许)
        if content.image_url and target_config.get("send_images", True):
            try:
                segments.append(MessageSegment.image(content.image_url))
            except Exception as e:
                logger.warning(f"添加图片失败: {e}")
        # 添加摘要(如果有)(欸这个我原来写了干什么的来着(?)
        if content.summary and content.summary != content.content:
            segments.append(MessageSegment.text(f"\n\n📝 摘要: {content.summary}"))

        return segments

    def _create_forward_node(self, content, target_config: Dict[str, Any]):
        """创建合并节点"""
        if not NONEBOT_AVAILABLE:
            return None
        try:
            message_segments = self._create_message_segments(content, target_config)  # 创建消息段
            if not message_segments:
                return None
            message = Message(message_segments)  # 构建消息
            node = {
                "type": "node",
                "data": {"name": "杳", "uin": "2134230390", "content": message},
            }
            return MessageSegment("node", node["data"])

        except Exception as e:
            logger.error(f"创建转发节点失败: {e}")
            return None

    async def send_group_message(self, content, target_config: Dict[str, Any]) -> bool:
        """发送群消息"""
        group_id = target_config.get("target_id")
        if not group_id:
            logger.error("未指定群号")
            return False
        if not self._check_rate_limit(group_id):
            return False
        bot = self._get_bot_instance()
        if not bot:
            return False

        try:
            if hasattr(content, "mentions") and content.mentions:
                mentioned_users = []
                for github_username in content.mentions:
                    qq_number = self.user_mappings.get(github_username)
                    if qq_number:
                        mentioned_users.append(f"{github_username}({qq_number})")
                    else:
                        mentioned_users.append(github_username)
                if mentioned_users:
                    github_users_text = "、".join(mentioned_users)
                    mention_text = f"\n\n📢 提及用户: {github_users_text}"
                    # 将提及信息添加到原始内容末尾
                    if hasattr(content, "content"):
                        content.content += mention_text
                    elif hasattr(content, "text"):
                        content.text += mention_text
                    else:
                        content = str(content) + mention_text

            forward_node = self._create_forward_node(content, target_config)
            if not forward_node:
                logger.error("创建转发节点失败")
                return False
            forward_message = Message([forward_node])
            result = await bot.send_group_forward_msg(group_id=int(group_id), messages=forward_message)

            logger.info(f"消息发送成功(QQ): 群{group_id}, 消息ID: {result.get('message_id')}")
            return True

        except ActionFailed as e:
            logger.error(f"消息发送失败(QQ) (ActionFailed): 群{group_id}, 错误: {e}")
            return False
        except NetworkError as e:
            logger.error(f"消息发送失败(QQ) (NetworkError): 群{group_id}, 错误: {e}")
            return False
        except Exception as e:
            logger.error(f"消息发送异常(QQ): 群{group_id}, 错误: {e}")
            return False

    async def send_private_message(self, content, target_config: Dict[str, Any]) -> bool:
        """发送私聊消息"""
        user_id = target_config.get("target_id")
        if not user_id:
            logger.error("未指定用户QQ号")
            return False
        if not self._check_rate_limit(f"private_{user_id}"):
            return False
        bot = self._get_bot_instance()
        if not bot:
            return False
        try:
            message_segments = self._create_message_segments(content, target_config)
            if not message_segments:
                logger.error("创建消息段失败")
                return False
            message = Message(message_segments)
            result = await bot.send_private_msg(user_id=int(user_id), message=message)
            logger.info(f"消息发送成功(QQ-私聊): 用户{user_id}, 消息ID: {result.get('message_id')}")
            return True

        except ActionFailed as e:
            logger.error(f"消息发送失败(QQ-私聊) (ActionFailed): 用户{user_id}, 错误: {e}")
            return False
        except NetworkError as e:
            logger.error(f"消息发送失败(QQ-私聊) (NetworkError): 用户{user_id}, 错误: {e}")
            return False
        except Exception as e:
            logger.error(f"消息发送异常(QQ-私聊): 用户{user_id}, 错误: {e}")
            return False

    async def send_message(self, content, target) -> bool:
        """发送QQ消息(统一入口)"""
        target_config = target.config or {}
        message_type = target_config.get("type", "group")  # 默认群消息
        if message_type == "group":
            return await self.send_group_message(content, target_config)
        elif message_type == "private":
            return await self.send_private_message(content, target_config)
        else:
            logger.error(f"不支持的QQ消息类型: {message_type}")
            return False

    async def send_aggregated_messages(self, messages, target) -> bool:
        """
        发送聚合消息(合并转发)

        Args:
            messages: 消息列表(PendingMessage对象)
            target: 发送目标

        Returns:
            bool: 是否发送成功
        """
        try:
            if not messages:
                return False
            target_config = target.config or {}
            group_id = target_config.get("target_id")
            if not group_id:
                logger.error("未指定群号")
                return False
            if not self._check_rate_limit(group_id):
                return False
            bot = self._get_bot_instance()
            if not bot:
                return False
            if not NONEBOT_AVAILABLE:
                logger.error("NB爆炸了(嗯对???")
                return False

            from nonebot.adapters.onebot.v11 import Message, MessageSegment

            all_mentions = set()
            for msg in messages:
                if hasattr(msg.content, "mentions") and msg.content.mentions:
                    all_mentions.update(msg.content.mentions)

            forward_nodes = []
            for i, msg in enumerate(messages):
                try:
                    content = msg.content
                    segments = self._create_message_segments(content, target_config)
                    if not segments:
                        continue
                    node_message = Message(segments)  # 创建转发节点
                    forward_node = MessageSegment.node_custom(user_id="2134230390", nickname="杳", content=node_message)
                    forward_nodes.append(forward_node)
                except Exception as e:
                    logger.warning(f"创建转发节点失败: {e}")
                    continue

            if not forward_nodes:
                logger.error("没有有效的转发节点")
                return False
            try:
                forward_message = Message(forward_nodes)
                result = await bot.send_group_forward_msg(group_id=int(group_id), messages=forward_message)

                logger.info(
                    f"聚合消息发送成功: 群{group_id}, 消息数: {len(forward_nodes)}, 消息ID: {result.get('message_id')}"
                )
                if all_mentions:
                    message_id = result.get("message_id")
                    await self._send_mention_message_with_reply(all_mentions, group_id, bot, message_id)

                return True
            except Exception as e:
                logger.error(f"聚合消息发送失败: 群{group_id}, 错误: {e}")
                return False

        except Exception as e:
            logger.error(f"发送聚合消息异常: {e}")
            return False

    async def _send_mention_message(self, mentions: set, group_id: str, bot) -> bool:
        """
        发送提及消息

        Args:
            mentions: 需要提及的GitHub用户名集合
            group_id: 群号
            bot: 机器人实例

        Returns:
            bool: 是否发送成功
        """
        try:
            if not mentions:
                return True

            from nonebot.adapters.onebot.v11 import Message, MessageSegment

            mention_segments = []
            mentioned_users = []

            for github_username in mentions:
                qq_number = self.user_mappings.get(github_username)
                if qq_number:
                    try:
                        mention_segments.append(MessageSegment.at(int(qq_number)))
                        mentioned_users.append(f"{github_username}({qq_number})")
                    except ValueError:
                        logger.warning(f"无效的QQ号: {qq_number}")
                        mentioned_users.append(github_username)
                else:
                    mentioned_users.append(github_username)
            if not mention_segments and not mentioned_users:
                return True

            message_parts = []
            if mention_segments:
                message_parts.extend(mention_segments)
                message_parts.append(MessageSegment.text(" "))

            # 简化提及消息格式，避免重复信息
            github_users_text = "、".join(mentioned_users)
            message_parts.append(MessageSegment.text(f"📢 提及用户: {github_users_text}"))

            mention_message = Message(message_parts)
            await bot.send_group_msg(group_id=int(group_id), message=mention_message)

            logger.info(f"提及消息发送成功: 群{group_id}, 提及用户: {mentioned_users}")
            return True

        except Exception as e:
            logger.error(f"发送提及消息失败: {e}")
            return False

    async def _send_mention_message_with_reply(self, mentions: set, group_id: str, bot, reply_message_id: int) -> bool:
        """
        发送引用指定消息的提及通知

        Args:
            mentions: 需要提及的GitHub用户名集合
            group_id: 群号
            bot: 机器人实例
            reply_message_id: 要引用的消息ID

        Returns:
            bool: 是否发送成功
        """
        try:
            if not mentions:
                return True

            from nonebot.adapters.onebot.v11 import Message, MessageSegment

            mention_segments = []
            mentioned_users = []

            for github_username in mentions:
                qq_number = self.user_mappings.get(github_username)
                if qq_number:
                    try:
                        mention_segments.append(MessageSegment.at(int(qq_number)))
                        mentioned_users.append(f"{github_username}({qq_number})")
                    except ValueError:
                        logger.warning(f"无效的QQ号: {qq_number}")
                        mentioned_users.append(github_username)
                else:
                    mentioned_users.append(github_username)

            if not mention_segments and not mentioned_users:
                return True
            message_parts = []
            if reply_message_id:
                message_parts.append(MessageSegment.reply(reply_message_id))
            if mention_segments:
                message_parts.extend(mention_segments)
                message_parts.append(MessageSegment.text(" "))
            github_users_text = "、".join(mentioned_users)
            message_parts.append(MessageSegment.text(f"📢 上述消息提及了: {github_users_text}"))

            mention_message = Message(message_parts)
            await bot.send_group_msg(group_id=int(group_id), message=mention_message)

            logger.info(
                f"引用提及消息发送成功: 群{group_id}, 引用消息ID: {reply_message_id}, 提及用户: {mentioned_users}"
            )
            return True

        except ActionFailed as e:
            logger.warning(f"引用提及消息发送失败(ActionFailed): {e}, 尝试发送简化版本")
            try:
                simplified_message_parts = []
                if mention_segments:
                    simplified_message_parts.extend(mention_segments)
                    simplified_message_parts.append(MessageSegment.text(" "))
                github_users_text = "、".join(mentioned_users)
                simplified_message_parts.append(MessageSegment.text(f"📢 消息提及了: {github_users_text}"))
                
                simplified_message = Message(simplified_message_parts)
                await bot.send_group_msg(group_id=int(group_id), message=simplified_message)
                
                logger.info(f"简化版提及消息发送成功: 群{group_id}, 提及用户: {mentioned_users}")
                return True
            except Exception as retry_e:
                logger.error(f"简化版提及消息也发送失败: {retry_e}")
                return False
        except NetworkError as e:
            logger.warning(f"网络错误导致引用提及消息发送失败: {e}")
            return False
        except Exception as e:
            logger.error(f"发送引用提及消息失败: {e}")
            return False

    def get_group_info(self, group_id: str) -> Optional[Dict[str, Any]]:
        """获取群信息"""
        bot = self._get_bot_instance()
        if not bot:
            return None

        try:
            # 这里需要同步调用(有点问题)
            loop = asyncio.get_event_loop()
            if loop.is_running():
                task = asyncio.create_task(bot.get_group_info(group_id=int(group_id)))
                return None  # 无法在这里等待异步结果
            else:
                return asyncio.run(bot.get_group_info(group_id=int(group_id)))
        except Exception as e:
            logger.error(f"获取群信息失败: {e}")
            return None

    def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户信息"""
        bot = self._get_bot_instance()
        if not bot:
            return None

        try:
            # 同样的异步处理问题
            loop = asyncio.get_event_loop()
            if loop.is_running():
                task = asyncio.create_task(bot.get_stranger_info(user_id=int(user_id)))
                return None
            else:
                return asyncio.run(bot.get_stranger_info(user_id=int(user_id)))
        except Exception as e:
            logger.error(f"获取用户信息失败: {e}")
            return None

    def update_user_mappings(self, mappings: Dict[str, str]):
        """更新用户映射"""
        self.user_mappings.update(mappings)
        logger.info(f"更新用户映射: {len(mappings)} 个新映射")

    def add_user_mapping(self, github_username: str, qq_number: str):
        """添加单个用户映射"""
        self.user_mappings[github_username] = qq_number
        logger.info(f"添加用户映射: {github_username} -> {qq_number}")

    def remove_user_mapping(self, github_username: str):
        """移除用户映射"""
        if github_username in self.user_mappings:
            qq_number = self.user_mappings.pop(github_username)
            logger.info(f"移除用户映射: {github_username} -> {qq_number}")
            return True
        return False

    def get_user_mappings(self) -> Dict[str, str]:
        """获取所有用户映射"""
        return self.user_mappings.copy()

    def is_available(self) -> bool:
        """检查QQ消息功能是否可用"""
        return NONEBOT_AVAILABLE and self._get_bot_instance() is not None

    def get_status(self) -> Dict[str, Any]:
        """获取QQ消息发送器状态"""
        bot = self._get_bot_instance()

        return {
            "available": self.is_available(),
            "nonebot_installed": NONEBOT_AVAILABLE,
            "bot_connected": bot is not None,
            "bot_id": bot.self_id if bot else None,
            "user_mappings_count": len(self.user_mappings),
            "rate_limiter_groups": len(self.rate_limiter),
        }


class QQMessageHandler:
    """QQ消息处理器"""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.sender = QQMessageSender(config_manager)

    async def handle_message(self, content, target) -> bool:
        """处理QQ消息"""
        try:
            if not self.sender.is_available():
                logger.error("消息功能(qq)不可用")
                return False

            success = await self.sender.send_message(content, target)
            if success:
                logger.debug(f"消息处理成功(qq): {target.target_id}")
            else:
                logger.warning(f"消息处理失败(qq): {target.target_id}")
            return success

        except Exception as e:
            logger.error(f"消息处理异常(qq): {e}")
            return False

    def get_sender(self) -> QQMessageSender:
        """获取消息发送器"""
        return self.sender

    def reload_config(self):
        """重新加载配置"""
        self.sender._load_user_mappings()
        logger.info("QQ消息处理器配置已重新加载")

    async def handle_mute_command(self, bot, event) -> bool:
        """处理禁言命令

        Args:
            bot: Bot实例
            event: 消息事件

        Returns:
            bool: 是否处理了命令
        """
        try:
            message_text = str(event.message).strip()
            if not message_text.startswith("闭嘴"):
                return False
            duration = 10  # 默认10分钟
            parts = message_text.split()
            if len(parts) > 1:
                try:
                    duration = int(parts[1])
                    if duration <= 0 or duration > 1440:  # 限制在1-1440分钟(24小时)
                        duration = 10
                except ValueError:
                    duration = 10
            # 获取消息聚合器并设置禁言
            from . import get_bot

            webhook_bot = get_bot()
            if webhook_bot and hasattr(webhook_bot, "msg_aggregator") and webhook_bot.msg_aggregator:
                webhook_bot.msg_aggregator.set_mute(duration)
                if NONEBOT_AVAILABLE:
                    from nonebot.adapters.onebot.v11 import MessageSegment

                    reply_msg = MessageSegment.reply(event.message_id)
                    response = f"好吧, 我睡{duration}分钟喵<(＿　＿)>"
                    await bot.send(event=event, message=reply_msg + response)
                logger.info(f"用户 {event.user_id} 设置了 {duration} 分钟的禁言")
                return True
            else:
                logger.warning("消息聚合器未初始化, 无法设置禁言")
                if NONEBOT_AVAILABLE:
                    from nonebot.adapters.onebot.v11 import MessageSegment

                    reply_msg = MessageSegment.reply(event.message_id)
                    response = f"不听不听 (｡•̀ᴗ-)✧"
                    await bot.send(event=event, message=reply_msg + response)
                return True
        except Exception as e:
            logger.error(f"处理禁言命令异常: {e}")
            try:
                if NONEBOT_AVAILABLE:
                    from nonebot.adapters.onebot.v11 import MessageSegment

                    reply_msg = MessageSegment.reply(event.message_id)
                    response = f"出了点小问题呢"
                    await bot.send(event=event, message=reply_msg + response)
            except:
                pass
            return True


# 全局QQ消息处理器实例
_qq_handler = None


def get_qq_handler(config_manager) -> QQMessageHandler:
    """获取全局QQ消息处理器实例"""
    global _qq_handler
    if _qq_handler is None:
        _qq_handler = QQMessageHandler(config_manager)
    return _qq_handler


def register_qq_platform():
    """注册到消息处理器"""
    try:
        from .conf import get_config_manager
        from .msg_req import MessagePlatform, get_message_processor

        config_manager = get_config_manager()
        message_processor = get_message_processor(config_manager)
        qq_handler = get_qq_handler(config_manager)
        message_processor.register_platform_handler(MessagePlatform.QQ, qq_handler.handle_message)
        logger.debug("QQ消息已注册到消息处理器")
    except Exception as e:
        logger.error(f"注册QQ平台失败: {e}")


def cleanup_qq_handler():
    """清理消息处理器资源"""
    global _qq_handler
    if _qq_handler:
        _qq_handler = None


if NONEBOT_AVAILABLE:
    try:
        register_qq_platform()
    except Exception as e:
        logger.debug(f"自动注册QQ平台时出错(好像挺正常的。: {e}")
