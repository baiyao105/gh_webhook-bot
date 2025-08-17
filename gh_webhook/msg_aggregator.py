"""
消息聚合管理器
"""

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime

from loguru import logger


@dataclass
class PendingMessage:
    """待发送消息"""

    content: Any  # MessageContent对象
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AggregationGroup:
    """聚合组"""

    key: str  # 聚合键
    messages: List[PendingMessage] = field(default_factory=list)
    timer: Optional[threading.Timer] = None
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)


class MessageAggregator:
    """消息聚合器"""

    def __init__(self, config_manager, message_processor):
        self.config_manager = config_manager
        self.message_processor = message_processor
        self.aggregation_groups: Dict[str, AggregationGroup] = {}
        self.groups_lock = threading.Lock()
        self.mute_until: float = 0.0  # 临时禁言配置
        self.mute_lock = threading.Lock()  # 临时禁言配置
        self.default_delay = 5  # 默认聚合延迟5秒
        self.max_messages_per_group = 10  # 每组最大消息数

        try:
            self.main_loop = asyncio.get_running_loop()
        except RuntimeError:
            self.main_loop = None
            logger.warning("无法获取当前事件循环")

        # logger.success("消息聚合器已初始化")

    def set_mute(self, duration_minutes: int = 10):
        """设置临时禁言

        Args:
            duration_minutes: 禁言时长(分钟), 默认10分钟
        """
        with self.mute_lock:
            self.mute_until = time.time() + (duration_minutes * 60)
            logger.info(f"设置临时禁言 {duration_minutes} 分钟, 到期时间: {datetime.fromtimestamp(self.mute_until)}")

    def is_muted(self) -> bool:
        """检查是否处于禁言状态"""
        with self.mute_lock:
            return time.time() < self.mute_until

    def get_mute_remaining(self) -> float:
        """获取剩余禁言时间(秒)"""
        with self.mute_lock:
            if time.time() < self.mute_until:
                return self.mute_until - time.time()
            return 0.0

    async def add_message(self, aggregation_key: str, message_content: Any, targets: List[Any]) -> bool:
        """添加消息到聚合队列

        Args:
            aggregation_key: 聚合键
            message_content: 消息内容
            targets: 发送目标列表

        Returns:
            bool: 是否成功添加
        """
        if self.is_muted():
            remaining = self.get_mute_remaining()
            logger.debug(f"处于禁言状态, 跳过消息。剩余时间: {remaining:.1f}秒")
            return False
        try:
            # 创建待发送消息
            pending_msg = PendingMessage(content=message_content, metadata={"targets": targets})
            with self.groups_lock:
                if aggregation_key not in self.aggregation_groups:
                    self.aggregation_groups[aggregation_key] = AggregationGroup(key=aggregation_key)
                group = self.aggregation_groups[aggregation_key]
                if group.timer and group.timer.is_alive():
                    group.timer.cancel()
                group.messages.append(pending_msg)
                group.last_updated = time.time()
                # 限制每组最大消息数
                if len(group.messages) > self.max_messages_per_group:
                    group.messages = group.messages[-self.max_messages_per_group :]
                    logger.warning(f"聚合组 {aggregation_key} 消息数超限, 保留最新 {self.max_messages_per_group} 条")

                config = self.config_manager.get_config()
                delay = config.get("aggregation_delay", self.default_delay)

                def timer_callback():
                    # 在主事件循环中安全执行异步任务
                    try:
                        if self.main_loop and not self.main_loop.is_closed():
                            asyncio.run_coroutine_threadsafe(
                                self._send_aggregated_messages(aggregation_key),
                                self.main_loop,
                            )
                        else:
                            logger.warning(f"主事件循环不可用, 无法发送聚合消息: {aggregation_key}")
                    except Exception as e:
                        logger.error(f"定时器回调执行失败: {e}")

                group.timer = threading.Timer(delay, timer_callback)
                group.timer.daemon = True
                group.timer.start()

                logger.debug(
                    f"消息已添加到聚合组 {aggregation_key}, 当前消息数: {len(group.messages)}, 延迟: {delay}秒"
                )

            return True

        except Exception as e:
            logger.error(f"添加消息到聚合队列失败: {e}")
            return False

    async def _send_aggregated_messages(self, aggregation_key: str):
        """发送聚合的消息

        Args:
            aggregation_key: 聚合键
        """
        try:
            if self.is_muted():
                remaining = self.get_mute_remaining()
                logger.debug(f"处于禁言状态, 跳过发送聚合消息。剩余时间: {remaining:.1f}秒")
                return

            with self.groups_lock:
                if aggregation_key not in self.aggregation_groups:
                    return

                group = self.aggregation_groups[aggregation_key]
                if not group.messages:
                    del self.aggregation_groups[aggregation_key]  # 清理空组
                    return

                messages_to_send = group.messages.copy()
                targets = messages_to_send[0].metadata.get("targets", []) if messages_to_send else []
                del self.aggregation_groups[aggregation_key]  # 清理组

            if not messages_to_send or not targets:
                logger.warning(f"聚合组 {aggregation_key} 没有有效的消息或目标")
                return
            success_count = 0
            total_count = len(targets)

            for target in targets:
                try:
                    success = await self._send_aggregated_to_target(
                        messages_to_send, target
                    )  # 为每个目标发送聚合的消息
                    if success:
                        success_count += 1

                except Exception as e:
                    logger.error(f"发送聚合消息到目标失败: {target}, 错误: {e}")

            logger.info(
                f"聚合消息发送完成: {aggregation_key}, 成功: {success_count}/{total_count}, 消息数: {len(messages_to_send)}"
            )

        except Exception as e:
            logger.error(f"发送聚合消息异常: {aggregation_key}, 错误: {e}")

    async def _send_aggregated_to_target(self, messages: List[PendingMessage], target: Any) -> bool:
        """向单个目标发送聚合消息

        Args:
            messages: 待发送消息列表
            target: 发送目标

        Returns:
            bool: 是否发送成功
        """
        try:
            handler = self.message_processor.platform_handlers.get(target.platform)
            if not handler:
                logger.warning(f"未找到平台 {target.platform.value} 的处理器")
                return False
            # 如果只有一条消息, 直接发送
            if len(messages) == 1:
                return await handler(messages[0].content, target)
            if target.platform.value == "qq":
                return await self._send_qq_aggregated_messages(messages, target, handler)
            else:
                success_count = 0
                for msg in messages:
                    if await handler(msg.content, target):
                        success_count += 1
                return success_count > 0

        except Exception as e:
            logger.error(f"向目标发送聚合消息异常: {e}")
            return False

    async def _send_qq_aggregated_messages(self, messages: List[PendingMessage], target: Any, handler) -> bool:
        """发送QQ聚合消息(合并转发)

        Args:
            messages: 消息列表
            target: QQ目标
            handler: QQ处理器

        Returns:
            bool: 是否发送成功
        """
        try:
            from .qq_msg import QQMessageHandler

            if hasattr(handler, "__self__") and isinstance(handler.__self__, QQMessageHandler):
                qq_handler = handler.__self__
                sender = qq_handler.get_sender()
                return await sender.send_aggregated_messages(messages, target)
            else:
                # 回退到逐条发送
                success_count = 0
                for msg in messages:
                    if await handler(msg.content, target):
                        success_count += 1
                return success_count > 0

        except Exception as e:
            logger.error(f"发送QQ聚合消息异常: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """获取聚合器状态"""
        with self.groups_lock:
            groups_info = {}
            for key, group in self.aggregation_groups.items():
                groups_info[key] = {
                    "message_count": len(group.messages),
                    "created_at": datetime.fromtimestamp(group.created_at).isoformat(),
                    "last_updated": datetime.fromtimestamp(group.last_updated).isoformat(),
                    "timer_active": group.timer and group.timer.is_alive(),
                }

        mute_remaining = self.get_mute_remaining()

        return {
            "active_groups": len(self.aggregation_groups),
            "groups_detail": groups_info,
            "muted": self.is_muted(),
            "mute_remaining_seconds": mute_remaining,
            "mute_remaining_minutes": mute_remaining / 60 if mute_remaining > 0 else 0,
        }

    def cleanup(self):
        """清理资源"""
        with self.groups_lock:
            # 取消所有定时器
            for group in self.aggregation_groups.values():
                if group.timer and group.timer.is_alive():
                    group.timer.cancel()
            self.aggregation_groups.clear()  # 清空聚合组
        logger.debug("消息聚合器已清理")


# 全局消息聚合器实例
_message_aggregator = None


def get_message_aggregator(config_manager=None, message_processor=None) -> MessageAggregator:
    """获取全局消息聚合器实例"""
    global _message_aggregator
    if _message_aggregator is None:
        if config_manager is None or message_processor is None:
            raise ValueError("创建必须提供config_manager和message_processor参数")
        _message_aggregator = MessageAggregator(config_manager, message_processor)
    return _message_aggregator


async def cleanup_message_aggregator():
    """清理消息聚合器资源"""
    global _message_aggregator
    if _message_aggregator:
        await _message_aggregator.cleanup()
        _message_aggregator = None
        logger.info("消息聚合器资源已清理")
