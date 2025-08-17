"""
GitHub Webhook Bot on nb
"""

import sys
from loguru import logger
import asyncio
import atexit
from pathlib import Path
from typing import Any, Dict

current_dir = Path(__file__).parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))
try:
    from .ai_handler import cleanup_unified_ai_handler, get_unified_ai_handler
    from .api import cleanup_api_server, get_api_server
    from .conf import cleanup_config, get_config_manager
    from .gh_rest import cleanup_github_processor, get_github_processor
    from .msg_req import cleanup_message_processor, get_message_processor
    from .og_img import cleanup_og_manager, get_og_manager
    from .qq_msg import cleanup_qq_handler, get_qq_handler
    from .utils import cleanup_utils, get_utils_instance
    from .webhook import cleanup_webhook_processor, get_webhook_processor
    from .msg_aggregator import cleanup_message_aggregator, get_message_aggregator
    from .mcp import cleanup_mcp_tools
except ImportError as e:
    logger.error(f"导入模块失败: {e}")
    raise

Plugin_Info = {
    "name": "GitHub Webhook Bot",
    "version": "1.0.0",
    "author": "baiyao105",
    "description": ".",
    "usage": ".",
}

CONFIG_FILE = current_dir / "config.json"
CACHE_DIR = current_dir / "cache"
IMAGE_CACHE_DIR = CACHE_DIR / "images"
LOGS_DIR = current_dir / "logs"
LOCK_DIR = current_dir / "locks"

for directory in [CACHE_DIR, IMAGE_CACHE_DIR, LOGS_DIR, LOCK_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

logger.remove()
logger.add(
    LOGS_DIR / "webhook_bot.log",
    format="{time:MM-DD HH:mm:ss} | {level: <8} | {name} | {message}",
    level="INFO",
    encoding="utf-8",
    rotation="10 MB",
    retention="7 days",
)
logger.add(
    lambda msg: print(msg, end=""),
    format="<green>{time:MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> | <level>{message}</level>",
    level="INFO",
    colorize=True,
)


class WebhookBot:
    """主类"""

    def __init__(self):
        self.config_manager = None
        self.utils = None
        self.og_manager = None
        self.unified_ai_handler = None
        self.msg_processor = None
        self.qq_handler = None
        self.github_processor = None
        self.webhook_processor = None
        self.api_server = None
        self.msg_aggregator = None
        self.initialized = False
        self.running = False

    async def initialize(self) -> bool:
        """初始化"""
        if self.initialized:
            return True
        try:
            # logger.debug("开始初始化")
            self.config_manager = get_config_manager()
            # logger.debug("配置管理器初始化成功")
            self.utils = get_utils_instance()
            # logger.debug("utils初始化成功")
            image_cache_days = self.config_manager.get("image_cache_days", 4)
            self.og_manager = get_og_manager(str(IMAGE_CACHE_DIR), image_cache_days)
            # logger.debug("og_manager初始化成功")
            self.unified_ai_handler = get_unified_ai_handler(self.config_manager)
            # logger.debug("unified_ai_handler初始化成功")
            self.msg_processor = get_message_processor(self.config_manager)
            # logger.debug("msg_processor初始化成功")
            self.msg_aggregator = get_message_aggregator(self.config_manager, self.msg_processor)
            # logger.debug("msg_aggregator初始化成功")
            self.qq_handler = get_qq_handler(self.config_manager)
            # logger.debug("qq_handler初始化成功")
            self.github_processor = get_github_processor(self.config_manager)
            # logger.debug("github_processor初始化成功")
            self.webhook_processor = get_webhook_processor(self.config_manager)
            # logger.debug("webhook_processor初始化成功")
            self.api_server = get_api_server(self.config_manager, self.webhook_processor)
            # logger.debug("api_server初始化成功")
            await self._setup_dependencies()
            # logger.debug("依赖关系设置完成")
            self.initialized = True
            return True

        except Exception as e:
            logger.error(f"初始化失败: {e}")
            await self.cleanup()
            return False

    async def _setup_dependencies(self):
        """设置依赖关系"""
        self.webhook_processor.set_dependencies(
            self.utils,
            self.msg_processor,
            self.github_processor,
            self.unified_ai_handler,
        )
        from .msg_req import MessagePlatform

        self.msg_processor.register_platform_handler(MessagePlatform.QQ, self.qq_handler.handle_message)
        if hasattr(self.qq_handler, "set_og_manager"):
            self.qq_handler.set_og_manager(self.og_manager)

    async def start(self) -> bool:
        """启动服务"""
        if not self.initialized:
            logger.error("Bot未初始化")
            return False

        if self.running:
            logger.warning("已在运行中")
            return True

        try:
            await self.webhook_processor.start_processing()
            if not self.api_server.start_server():
                raise Exception("API服务器启动失败")
            if hasattr(self.qq_handler, "start") and callable(self.qq_handler.start):
                await self.qq_handler.start()
            self.running = True
            # server_info = self.api_server.get_server_info()
            # logger.info(f"服务器运行在: {server_info.get('url')}")
            # logger.info(f"Webhook地址: {server_info.get('webhook_url')}")
            return True
        except Exception as e:
            logger.error(f"启动服务失败: {e}")
            await self.stop()
            return False

    async def stop(self) -> bool:
        """停止服务"""
        if not self.running:
            logger.info("服务未在运行")
            return True

        try:
            logger.info("停止服务...")
            if self.api_server:
                self.api_server.stop_server()
            if self.webhook_processor:
                await self.webhook_processor.stop_processing()
            if hasattr(self.qq_handler, "stop") and callable(self.qq_handler.stop):
                await self.qq_handler.stop()
            if self.msg_aggregator:
                await cleanup_message_aggregator()
            self.running = False
            logger.info("服务已停止")
            return True

        except Exception as e:
            logger.error(f"停止服务失败: {e}")
            return False

    async def restart(self) -> bool:
        """重启服务"""
        logger.info("重启服务...")
        await self.stop()
        # 等一下
        await asyncio.sleep(1)
        if self.config_manager:
            self.config_manager.reload_config()
        return await self.start()

    def get_status(self) -> Dict[str, Any]:
        """获取状态信息"""
        status = {
            "initialized": self.initialized,
            "running": self.running,
            "components": {},
        }
        if self.initialized:
            if self.api_server:
                status["components"]["api_server"] = self.api_server.get_server_info()
            if self.webhook_processor:
                status["components"]["webhook_processor"] = self.webhook_processor.get_stats()
            if self.qq_handler and hasattr(self.qq_handler, "get_status"):
                status["components"]["qq_handler"] = self.qq_handler.get_status()
            if self.unified_ai_handler and hasattr(self.unified_ai_handler, "get_status"):
                status["components"]["unified_ai_handler"] = self.unified_ai_handler.get_status()

        return status

    async def cleanup(self):
        """清理所有资源"""
        logger.info("清理gh wb资源...")
        try:
            # 停止服务
            await self.stop()
            async_cleanup_tasks = [
                cleanup_webhook_processor(),
                cleanup_github_processor(),
                cleanup_mcp_tools(),
            ]
            await asyncio.gather(*async_cleanup_tasks, return_exceptions=True)
            sync_cleanup_functions = [
                cleanup_api_server,
                cleanup_qq_handler,
                cleanup_message_processor,
                cleanup_unified_ai_handler,
                cleanup_og_manager,
                cleanup_utils,
                cleanup_config,
            ]
            # 清理聚合器
            try:
                await cleanup_message_aggregator()
            except Exception as e:
                logger.error(f"清理消息聚合器失败: {e}")

            for cleanup_func in sync_cleanup_functions:
                try:
                    cleanup_func()
                except Exception as e:
                    logger.error(f"清理函数 {cleanup_func.__name__} 失败: {e}")
            self.initialized = False
            self.running = False
            logger.info("资源清理完成")

        except Exception as e:
            logger.critical(f"清理资源异常: {e}")


# 全局实例
_bot_instance = None


def get_bot() -> WebhookBot:
    """获取全局实例"""
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = WebhookBot()
    return _bot_instance


async def cleanup_bot():
    """清理资源"""
    global _bot_instance
    if _bot_instance:
        await _bot_instance.cleanup()
        _bot_instance = None


# 注册清理函数
atexit.register(lambda: asyncio.run(cleanup_bot()))
try:
    from nonebot import on_command, on_message
    from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
    from nonebot.permission import SUPERUSER
    from nonebot.rule import to_me

    webhook_bot = get_bot()

    from . import on_qq_msg

    start_webhook = on_command("webhook start", permission=SUPERUSER, priority=1, block=True)

    @start_webhook.handle()
    async def handle_start_webhook(bot: Bot, event: MessageEvent):
        """启动webhook服务"""
        try:
            from nonebot.adapters.onebot.v11 import MessageSegment

            if not webhook_bot.initialized:
                success = await webhook_bot.initialize()
                if not success:
                    reply_msg = MessageSegment.reply(event.message_id)
                    await start_webhook.send(reply_msg + "初始化失败,去似吧.")
                    return

            if webhook_bot.running:
                reply_msg = MessageSegment.reply(event.message_id)
                await start_webhook.send(reply_msg + "服务已在运行中(哈哈")
                return

            success = await webhook_bot.start()
            if success:
                server_info = webhook_bot.api_server.get_server_info()
                message = f"Webhook服务启动成功!\n监听地址: {server_info.get('url')}"
                reply_msg = MessageSegment.reply(event.message_id)
                await start_webhook.send(reply_msg + message)
            else:
                reply_msg = MessageSegment.reply(event.message_id)
                await start_webhook.send(reply_msg + "服务启动失败,去似吧.")

        except Exception as e:
            logger.error(f"启动webhook服务异常: {e}")
            reply_msg = MessageSegment.reply(event.message_id)
            await start_webhook.send(reply_msg + f"启动异常: {str(e)}")

    stop_webhook = on_command("webhook stop", permission=SUPERUSER, priority=1, block=True)

    @stop_webhook.handle()
    async def handle_stop_webhook(bot: Bot, event: MessageEvent):
        """停止webhook服务"""
        try:
            from nonebot.adapters.onebot.v11 import MessageSegment

            if not webhook_bot.running:
                reply_msg = MessageSegment.reply(event.message_id)
                await stop_webhook.send(reply_msg + "服务未在运行")
                return

            success = await webhook_bot.stop()
            if success:
                reply_msg = MessageSegment.reply(event.message_id)
                await stop_webhook.send(reply_msg + "服务已停止")
            else:
                reply_msg = MessageSegment.reply(event.message_id)
                await stop_webhook.send(reply_msg + "服务停止失败,去似吧.")

        except Exception as e:
            logger.error(f"停止webhook服务异常: {e}")
            reply_msg = MessageSegment.reply(event.message_id)
            await stop_webhook.send(reply_msg + f"停止异常: {str(e)}")

    restart_webhook = on_command("webhook restart", permission=SUPERUSER, priority=1, block=True)

    @restart_webhook.handle()
    async def handle_restart_webhook(bot: Bot, event: MessageEvent):
        """重启webhook服务"""
        try:
            from nonebot.adapters.onebot.v11 import MessageSegment

            success = await webhook_bot.restart()
            if success:
                server_info = webhook_bot.api_server.get_server_info()
                message = f"服务重启成功!\n 监听地址: {server_info.get('url')}"
                reply_msg = MessageSegment.reply(event.message_id)
                await restart_webhook.send(reply_msg + message)
            else:
                reply_msg = MessageSegment.reply(event.message_id)
                await restart_webhook.send(reply_msg + "服务重启失败,去似吧.")

        except Exception as e:
            logger.error(f"重启webhook服务异常: {e}")
            reply_msg = MessageSegment.reply(event.message_id)
            await restart_webhook.send(reply_msg + f"重启异常: {str(e)}")

    og_command = on_command("og", priority=1, block=True)

    @og_command.handle()
    async def handle_og_command(bot: Bot, event: MessageEvent):
        """生成OG图片"""
        try:
            from nonebot.adapters.onebot.v11 import MessageSegment

            if not webhook_bot.initialized:
                await webhook_bot.initialize()

            message_text = str(event.get_message()).strip()
            if message_text.startswith("/og"):
                args = message_text[3:].strip()
            elif message_text.startswith("og"):
                args = message_text[2:].strip()
            else:
                args = ""
            if not args:
                reply_msg = MessageSegment.reply(event.message_id)
                await og_command.send(reply_msg + "请提供URL\n用法: /og [-f] <URL>\n-f: 强制刷新, 不使用缓存")
                return

            force_refresh = False
            url = ""
            parts = args.split()
            for part in parts:
                if part == "-f":
                    force_refresh = True
                elif not url:  # 第一个非选项参数作为URL
                    url = part
            if not url:
                reply_msg = MessageSegment.reply(event.message_id)
                await og_command.send(reply_msg + "❌ 请提供URL\n用法: /og [-f] <URL>\n-f: 强制刷新, 不使用缓存")
                return
            if not (url.startswith("http://") or url.startswith("https://")):
                url = "https://" + url
            if webhook_bot.og_manager:
                if force_refresh and hasattr(webhook_bot.og_manager, "clear_url_cache"):
                    webhook_bot.og_manager.clear_url_cache(url)
                proxy_config = webhook_bot.config_manager.get("proxy", {}) if webhook_bot.config_manager else {}
                image_path = await webhook_bot.og_manager.get_og_image(url, force_refresh, proxy_config)
                if image_path and Path(image_path).exists():
                    # 获取图片信息
                    file_size = Path(image_path).stat().st_size
                    size_str = (
                        f"{file_size / 1024:.1f} KB"
                        if file_size < 1024 * 1024
                        else f"{file_size / (1024 * 1024):.1f} MB"
                    )
                    status_text = "🔄 强制刷新" if force_refresh else "📋 缓存获取"

                    try:
                        image_formats = [
                            Path(image_path).as_uri(),  # file:///C:/path/to/image.jpg
                            f"file:///{image_path}",     # 原格式
                            str(Path(image_path).absolute()),  # 绝对路径
                        ]

                        success = False
                        for img_format in image_formats:
                            try:
                                message_segments = [
                                    MessageSegment.reply(event.message_id),
                                    MessageSegment.image(img_format),
                                    MessageSegment.text(f"\n获得方法: {status_text}\n图片大小: {size_str}"),
                                ]
                                await og_command.send(message_segments)
                                success = True
                                logger.debug(f"图片发送成功，使用格式: {img_format}")
                                break
                            except Exception as send_error:
                                logger.debug(f"图片格式 {img_format} 发送失败: {send_error}")
                                continue

                        if not success:
                            reply_msg = MessageSegment.reply(event.message_id)
                            await og_command.send(reply_msg + f"✅ OG图片获取成功\n📁 路径: {image_path}\n📊 大小: {size_str}\n图片发送失败,但文件已保存")

                    except Exception as format_error:
                        logger.error(f"处理图片格式时出错: {format_error}")
                        reply_msg = MessageSegment.reply(event.message_id)
                        await og_command.send(reply_msg + f"图片处理失败: {str(format_error)}")
                else:
                    reply_msg = MessageSegment.reply(event.message_id)
                    await og_command.send(reply_msg + "获得OG图片失败")
            else:
                reply_msg = MessageSegment.reply(event.message_id)
                await og_command.send(reply_msg + "OG图片管理器未初始化")

        except Exception as e:
            logger.error(f"获得OG图片异常: {e}")
            try:
                reply_msg = MessageSegment.reply(event.message_id)
                await og_command.send(reply_msg + f"获取时时发生异常\n错误信息: {str(e)}")
            except Exception as send_error:
                logger.error(f"发送错误消息失败: {send_error}")

    webhook_status = on_command("webhook info", permission=SUPERUSER, priority=1, block=True)

    @webhook_status.handle()
    async def handle_webhook_status(bot: Bot, event: MessageEvent):
        """查询webhook状态"""
        try:
            from nonebot.adapters.onebot.v11 import MessageSegment

            status = webhook_bot.get_status()
            message_lines = [
                f"Webhook状态",
                f"初始化: {'✅' if status['initialized'] else '❌'}",
                f"运行中: {'✅' if status['running'] else '❌'}",
            ]
            if status["initialized"]:
                components = status.get("components", {})
                api_info = components.get("api_server", {})
                if api_info:
                    message_lines.extend(
                        [
                            "",
                            "服务器:",
                            f"  状态: {'运行中' if api_info.get('running') else '已停止'}",
                            f"  地址: {api_info.get('url', 'N/A')}",
                        ]
                    )
                webhook_info = components.get("webhook_processor", {})
                if webhook_info:
                    message_lines.extend(
                        [
                            "",
                            "处理器:",
                            f"  处理中: {'是' if webhook_info.get('is_processing') else '否'}",
                            f"  队列大小: {webhook_info.get('queue_size', 0)}",
                            f"  总事件数: {webhook_info.get('total_events', 0)}",
                        ]
                    )
            reply_msg = MessageSegment.reply(event.message_id)
            await webhook_status.send(reply_msg + "\n".join(message_lines))

        except Exception as e:
            logger.error(f"查询webhook状态异常: {e}")
            reply_msg = MessageSegment.reply(event.message_id)
            await webhook_status.send(reply_msg + f"查询状态异常: {str(e)}")

    mute_command = on_command("闭嘴", priority=1, block=True)
    mute_command_with_at = on_command("闭嘴", rule=to_me(), priority=1, block=True)
    mute_command_slash = on_command("/闭嘴", priority=1, block=True)

    async def _handle_mute_command_logic(bot: Bot, event: MessageEvent, command_handler):
        """闭嘴的处理"""
        try:
            from nonebot.adapters.onebot.v11 import MessageSegment

            # 确保webhook_bot已经初始化
            if not webhook_bot.initialized:
                logger.info("webhook_bot未初始化，正在初始化...")
                success = await webhook_bot.initialize()
                if not success:
                    reply_msg = MessageSegment.reply(event.message_id)
                    await command_handler.send(reply_msg + "初始化失败，无法处理闭嘴命令 (｡•́︿•̀｡)")
                    return

            qq_handler = (
                webhook_bot.qq_handler if hasattr(webhook_bot, "qq_handler") and webhook_bot.qq_handler else None
            )
            if not qq_handler:
                reply_msg = MessageSegment.reply(event.message_id)
                await command_handler.send(reply_msg + "QQ消息处理器未初始化 (｡•́︿•̀｡)")
                return

            success = await qq_handler.handle_mute_command(bot, event)
            if not success:
                reply_msg = MessageSegment.reply(event.message_id)
                await command_handler.send(reply_msg + "禁言设置失败了呢 (｡•́︿•̀｡)")

        except Exception as e:
            logger.error(f"处理闭嘴命令异常: {e}")
            from nonebot.adapters.onebot.v11 import MessageSegment

            reply_msg = MessageSegment.reply(event.message_id)
            await command_handler.send(reply_msg + f"出错了: {str(e)}")

    @mute_command.handle()
    async def handle_mute_command(bot: Bot, event: MessageEvent):
        """处理闭嘴命令"""
        await _handle_mute_command_logic(bot, event, mute_command)

    @mute_command_with_at.handle()
    async def handle_mute_command_with_at(bot: Bot, event: MessageEvent):
        """处理闭嘴命令"""
        await _handle_mute_command_logic(bot, event, mute_command_with_at)

    @mute_command_slash.handle()
    async def handle_mute_command_slash(bot: Bot, event: MessageEvent):
        """处理闭嘴命令"""
        await _handle_mute_command_logic(bot, event, mute_command_slash)

except ImportError:
    logger.warning("依赖似了(句号")

__all__ = ["Plugin_Info", "WebhookBot", "get_bot", "cleanup_bot"]

# logger.info(f"{Plugin_Info['name']} v{Plugin_Info['version']} 加载完成！")
