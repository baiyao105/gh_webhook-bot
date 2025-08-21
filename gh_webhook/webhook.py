"""
Webhook事件调度
"""

import asyncio
import json
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from loguru import logger

try:
    from .ai_handler import get_unified_ai_handler
except ImportError:
    try:
        from ai_handler import get_unified_ai_handler
    except ImportError:
        get_unified_ai_handler = None
        logger.warning("统一AI处理器模块导入失败, 相关功能将不可用")

try:
    from .mcp import MCPTools
except ImportError:
    try:
        from mcp import MCPTools
    except ImportError:
        MCPTools = None
        logger.warning("MCP工具模块导入失败, 相关功能将不可用")


class WebhookEventType(Enum):
    """Webhook事件类型"""

    PUSH = "push"
    PULL_REQUEST = "pull_request"
    ISSUES = "issues"
    ISSUE_COMMENT = "issue_comment"
    PULL_REQUEST_REVIEW = "pull_request_review"
    PULL_REQUEST_REVIEW_COMMENT = "pull_request_review_comment"
    RELEASE = "release"
    STAR = "star"
    FORK = "fork"
    WATCH = "watch"
    CREATE = "create"
    DELETE = "delete"
    WORKFLOW_RUN = "workflow_run"
    WORKFLOW_JOB = "workflow_job"
    REPOSITORY = "repository"
    PING = "ping"


@dataclass
class WebhookEvent:
    """Webhook事件数据类"""

    event_type: str
    delivery_id: str
    signature: str
    payload: Dict[str, Any]
    headers: Dict[str, str]
    timestamp: str
    repository: Optional[str] = None
    processed: bool = False
    error: Optional[str] = None
    raw_body: Optional[bytes] = None  # 原始请求体字节数据, 用于签名验证


class WebhookProcessor:
    """Webhook处理器"""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.utils = None  # 将在初始化时设置
        self.msg_processor = None  # 消息处理器
        self.github_processor = None  # GitHub处理器
        self.unified_ai_handler = None  # 统一AI处理器
        self.event_stats = defaultdict(int)
        self.last_reset_time = time.time()
        self.delivery_cache = {}  # delivery_id -> timestamp
        self.cache_ttl = 3600  # 1小时
        self.event_queue = asyncio.Queue(maxsize=1000)
        self.processing_task = None
        self.is_processing = False
        self.active_reviews = set()  # 正在进行的审查: {"repo/name#pr_number"}
        self.review_cache_max_size = 100
        # 支持的类型
        self.supported_events = {
            WebhookEventType.PUSH.value,
            WebhookEventType.PULL_REQUEST.value,
            WebhookEventType.ISSUES.value,
            WebhookEventType.ISSUE_COMMENT.value,
            WebhookEventType.PULL_REQUEST_REVIEW.value,
            WebhookEventType.PULL_REQUEST_REVIEW_COMMENT.value,
            WebhookEventType.RELEASE.value,
            WebhookEventType.STAR.value,
            WebhookEventType.FORK.value,
            WebhookEventType.WATCH.value,
            WebhookEventType.CREATE.value,
            WebhookEventType.DELETE.value,
            WebhookEventType.WORKFLOW_RUN.value,
            WebhookEventType.WORKFLOW_JOB.value,
            WebhookEventType.REPOSITORY.value,
            WebhookEventType.PING.value,
        }

    def set_dependencies(self, utils_module, msg_processor, github_processor, unified_ai_handler):
        """设置依赖模块"""
        self.utils = utils_module
        self.msg_processor = msg_processor
        self.github_processor = github_processor
        self.unified_ai_handler = unified_ai_handler

        if self.unified_ai_handler:
            mcp_tools = None
            if MCPTools:
                try:
                    # 需要导入ContextManager来创建MCP工具实例
                    from .ai_models import ContextManager
                    from pathlib import Path

                    context_manager = ContextManager(Path("ai_contexts"))
                    mcp_tools = MCPTools(self.config_manager, context_manager, "webhook")
                    logger.success("MCP工具实例创建成功")
                except Exception as e:
                    logger.error(f"MCP工具实例创建失败: {e}")

            self.unified_ai_handler.set_dependencies(github_processor, mcp_tools=mcp_tools)
            asyncio.create_task(self._initialize_unified_ai())

        logger.success("事件处理器依赖模块已设置")

    async def _initialize_unified_ai(self):
        """初始化统一AI处理器"""
        try:
            if hasattr(self, "unified_ai_handler") and self.unified_ai_handler:
                # 先初始化MCP工具
                if self.unified_ai_handler.mcp_tools:
                    logger.info("开始初始化MCP工具...")
                    mcp_success = await self.unified_ai_handler.mcp_tools.initialize()
                    if mcp_success:
                        logger.success("MCP工具初始化成功 ✨")
                    else:
                        logger.error("MCP工具初始化失败 ❌")
                else:
                    logger.warning("MCP工具不可用")

                # 再初始化AI处理器
                logger.info("开始初始化AI处理器...")
                success = await self.unified_ai_handler.initialize()
                if success:
                    logger.success("AI处理器初始化成功 ♪(´▽｀)")
                else:
                    logger.error("AI处理器初始化失败")
            else:
                logger.warning("AI处理器不可用")
        except Exception as e:
            logger.error(f"AI处理器初始化异常: {e}")

    async def start_processing(self):
        """开始处理事件队列"""
        if self.is_processing:
            logger.warning("事件处理已在运行中")
            return

        self.is_processing = True
        self.processing_task = asyncio.create_task(self._process_event_queue())

    async def stop_processing(self):
        """停止处理事件队列"""
        if not self.is_processing:
            return

        self.is_processing = False

        if self.processing_task:
            self.processing_task.cancel()
            try:
                await self.processing_task
            except asyncio.CancelledError:
                pass

        logger.info("事件处理器已停止")

    async def process_webhook(self, webhook_data: Dict[str, Any]) -> bool:
        """处理webhook请求"""
        try:
            event = WebhookEvent(
                event_type=webhook_data.get("event_type", ""),
                delivery_id=webhook_data.get("delivery_id", ""),
                signature=webhook_data.get("signature", ""),
                payload=webhook_data.get("payload", {}),
                headers=webhook_data.get("headers", {}),
                timestamp=webhook_data.get("timestamp", datetime.now().isoformat()),
                raw_body=webhook_data.get("raw_body"),  # 传递原始字节数据
            )

            # 基础验证
            if not self._validate_event(event):
                return False
            event.repository = self._extract_repository_name(event.payload)
            if self._is_duplicate_delivery(event.delivery_id):
                logger.info(f"跳过重复投递: {event.delivery_id}")
                return True
            if not event.repository:
                logger.warning(f"无法提取仓库名称: {event.delivery_id}")
                return False
            repo_config = self.config_manager.get_repository_config(event.repository)
            if not repo_config:
                logger.info(f"仓库 {event.repository} 未在配置文件中, 跳过处理")
                return True
            if not self._is_repository_enabled(event.repository):
                logger.info(f"仓库未启用webhook: {event.repository}")
                return True

            signature_valid = await self._verify_webhook_signature(event)
            # logger.info(f"签名验证结果: {signature_valid} for {event.delivery_id}")
            if not signature_valid:
                logger.warning(f"Webhook签名验证失败: {event.delivery_id}")
                return False
            try:
                await self.event_queue.put(event)
                logger.info(f"事件已加入处理队列: {event.event_type} - {event.repository} - {event.delivery_id}")
                return True
            except asyncio.QueueFull:
                logger.error(f"事件队列已满, 丢弃事件: {event.delivery_id}")
                return False

        except Exception as e:
            logger.error(f"处理webhook异常: {e}")
            return False

    def _validate_event(self, event: WebhookEvent) -> bool:
        """验证事件基础信息"""
        if not event.event_type:
            logger.warning("缺少事件类型")
            return False

        if not event.delivery_id:
            logger.warning("缺少投递ID")
            return False

        if not event.payload:
            logger.warning("缺少payload数据")
            return False

        if event.event_type not in self.supported_events:
            logger.info(f"不支持的事件类型: {event.event_type}")
            return False

        return True

    def _extract_repository_name(self, payload: Dict[str, Any]) -> Optional[str]:
        """提取仓库名称"""
        # logger.debug(f"开始提取仓库名称, payload类型: {type(payload)}")
        if not payload:
            logger.warning("payload为空")
            return None

        if "payload" in payload:
            inner_payload = payload.get("payload", {})
            # logger.debug(f"webhook_data结构, 内部payload类型: {type(inner_payload)}")
            if inner_payload and isinstance(inner_payload, dict):
                repository = inner_payload.get("repository")
                # logger.debug(f"从内部payload提取到的repository字段: {repository}")
                if repository and isinstance(repository, dict):
                    full_name = repository.get("full_name")
                    # logger.debug(f"提取到的full_name: {full_name}")
                    return full_name
        else:
            repository = payload.get("repository")
            # logger.info(f"从直接payload提取到的repository字段: {repository}")
            if repository and isinstance(repository, dict):
                full_name = repository.get("full_name")
                # logger.debug(f"提取到的full_name: {full_name}")
                return full_name
        logger.warning("未找到有效的repository信息")
        return None

    def _is_duplicate_delivery(self, delivery_id: str) -> bool:
        """检查重复投递"""
        current_time = time.time()
        expired_keys = [
            key for key, timestamp in self.delivery_cache.items() if current_time - timestamp > self.cache_ttl
        ]
        for key in expired_keys:
            del self.delivery_cache[key]
        if delivery_id in self.delivery_cache:
            return True

        self.delivery_cache[delivery_id] = current_time
        return False

    async def _verify_webhook_signature(self, event: WebhookEvent) -> bool:
        """验证webhook签名"""
        if not event.repository:
            return False
        repo_config = self.config_manager.get_repository_config(event.repository)
        # logger.info(f"仓库 {event.repository} 配置查询结果: {repo_config}")
        webhook_config = repo_config.get("webhook", {})
        verify_signature = webhook_config.get("verify_signature", repo_config.get("verify_signature", True))
        logger.info(f"仓库 {event.repository} 签名验证设置: {verify_signature}")
        if not verify_signature:
            logger.info(f"仓库 {event.repository} 已禁用签名验证")
            return True
        if not self.utils:
            logger.warning("utils未初始化")
            return True
        secret = repo_config.get("webhook_secret")
        if not secret:
            logger.warning(f"仓库 {event.repository} 未配置webhook密钥")
            return False

        if event.raw_body is None:
            logger.warning("未找到原始body数据, 重新序列化数据验证..")
            payload_bytes = json.dumps(event.payload, separators=(",", ":")).encode("utf-8")
        else:
            payload_bytes = event.raw_body

        return self.utils["verify_github_signature"](payload_bytes, event.signature, secret)

    def _is_repository_enabled(self, repository: Optional[str]) -> bool:
        """检查仓库是否启用"""
        if not repository:
            return False
        repo_config = self.config_manager.get_repository_config(repository)
        if not repo_config:
            return False
        repo_enabled = repo_config.get("enabled", True)
        webhook_config = repo_config.get("webhook", {})
        webhook_enabled = webhook_config.get("enabled", True)
        return repo_enabled and webhook_enabled

    async def _process_event_queue(self):
        """处理事件队列"""
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while self.is_processing:
            try:
                event = await asyncio.wait_for(self.event_queue.get(), timeout=1.0)
                await self._handle_single_event(event)
                self.event_queue.task_done()
                consecutive_errors = 0  # 重置错误计数
                
            except asyncio.TimeoutError:
                # 超时是正常的
                continue
            except asyncio.CancelledError:
                logger.info("处理任务被取消")
                break
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"处理事件队列异常 [连续错误: {consecutive_errors}/{max_consecutive_errors}]: {e}")
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning(f"连续错误过多，暂停处理 30 秒")
                    await asyncio.sleep(30)
                    consecutive_errors = 0
                else:
                    await asyncio.sleep(min(consecutive_errors * 2, 10))  # 指数退避，最多10秒

    async def _handle_single_event(self, event: WebhookEvent):
        """处理单个事件"""
        try:
            logger.info(f"开始处理事件: {event.event_type} - {event.repository} - {event.delivery_id}")
            self.event_stats[event.event_type] += 1
            # 根据事件类型分发处理
            success = await self._dispatch_event(event)
            if success:
                event.processed = True
                logger.info(f"事件处理成功: {event.delivery_id}")
            else:
                event.error = "处理失败"
                logger.warning(f"事件处理失败: {event.delivery_id}")

        except Exception as e:
            event.error = str(e)
            logger.error(f"处理事件异常: {event.delivery_id} - {e}")

    async def _dispatch_event(self, event: WebhookEvent) -> bool:
        """分发事件到相应的处理器"""
        try:
            # 并行处理不同的任务
            tasks = []
            # 消息通知
            if self.msg_processor:
                tasks.append(self._handle_message_notification(event))
            # GH-API处理
            if self.github_processor and event.event_type in ["issues", "pull_request"]:
                tasks.append(self._handle_github_processing(event))
            # PR审核
            if event.event_type == "pull_request" and event.payload.get("action") in [
                "review_requested",
                "review_request_removed",
            ]:
                tasks.append(self._handle_review_request(event))
            # 统一AI处理
            if hasattr(self, "unified_ai_handler") and self.unified_ai_handler:
                if hasattr(self.unified_ai_handler, "mcp_tools") and self.unified_ai_handler.mcp_tools:
                    if hasattr(self.unified_ai_handler, "_is_mcp_tools_initialized"):
                        mcp_ready = self.unified_ai_handler._is_mcp_tools_initialized()
                    else:
                        mcp_ready = (
                            hasattr(self.unified_ai_handler.mcp_tools, "_initialized")
                            and self.unified_ai_handler.mcp_tools._initialized
                        )
                    if mcp_ready:
                        if event.event_type == "issue_comment":
                            tasks.append(self.unified_ai_handler.handle_issue_comment(event.payload))
                        elif event.event_type == "pull_request_review_comment":
                            tasks.append(self.unified_ai_handler.handle_pr_review_comment(event.payload))
                    else:
                        logger.warning(f"MCP工具未就绪, 跳过AI处理: {event.event_type} - {event.repository}")
                else:
                    logger.warning(f"MCP工具不可用, 跳过AI处理: {event.event_type} - {event.repository}")
            # 执行所有任务
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                success_count = 0
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(f"任务 {i} 执行异常: {result}")
                    elif result:
                        success_count += 1
                return success_count > 0
            return True

        except Exception as e:
            logger.error(f"分发事件异常: {e}")
            return False

    async def _handle_message_notification(self, event: WebhookEvent) -> bool:
        """处理消息通知"""
        try:
            if not self.msg_processor:
                return False
            if not self.config_manager.is_message_type_allowed(event.repository, event.event_type):
                logger.info(f"仓库 {event.repository} 不允许发送 {event.event_type} 类型的消息, 跳过处理")
                return True  # 不是错误, 只是跳过处理

            from .msg_req import MessageType

            try:
                event_type_mapping = {
                    "workflow_run": "workflow_run",
                    "pull_request": "pull_request",
                    "issue_comment": "issues",
                    "pull_request_review": "pull_request",
                    "pull_request_review_comment": "pull_request",
                }
                mapped_event_type = event_type_mapping.get(event.event_type, event.event_type)
                message_type = MessageType(mapped_event_type)
            except ValueError:
                logger.warning(f"不支持的消息类型: {event.event_type}")
                return True  # 不是错误, 只是不处理(lazy(

            # event.payload包含嵌套的payload结构
            actual_payload = event.payload.get("payload", event.payload)
            message_request = self.msg_processor.create_message_request(message_type, actual_payload, event.repository)
            if message_request:
                return await self.msg_processor.process_message_request(message_request)

            return True

        except Exception as e:
            logger.error(f"处理消息通知异常: {e}")
            return False

    async def _handle_github_processing(self, event: WebhookEvent) -> bool:
        """处理GitHub操作"""
        try:
            if not self.github_processor:
                return False
            actual_payload = event.payload.get("payload", event.payload)
            if event.event_type == "issues":
                return await self.github_processor.process_issue_event(actual_payload)
            elif event.event_type == "pull_request":
                return await self.github_processor.process_pr_event(actual_payload)
            return True

        except Exception as e:
            logger.error(f"处理GitHub操作异常: {e}")
            return False

    async def _handle_review_request(self, event: WebhookEvent) -> bool:
        """处理PR审核请求事件"""
        try:
            if not self.github_processor:
                return False
            repo_config = self.config_manager.get_repository_config(event.repository)
            if not repo_config:
                return True
            allow_review_config = repo_config.get("allow_review", {})
            if not isinstance(allow_review_config, dict) or not allow_review_config.get("enabled", False):
                return True
            bot_username = allow_review_config.get("bot_username", "")
            if not bot_username:
                logger.warning(f"仓库 {event.repository} 未配置用户名")
                return True
            # PR信息
            pr = event.payload.get("pull_request", {})
            pr_number = pr.get("number")
            action = event.payload.get("action")
            if not pr_number:
                return False
            owner, repo = event.repository.split("/")
            review_requests = await self.github_processor._get_api_client(event.repository).get_pr_review_requests(
                owner, repo, pr_number
            )
            requested_reviewers = [user["login"] for user in review_requests.get("users", [])]

            bot_requested = bot_username in requested_reviewers
            if action == "review_requested" and bot_requested:
                review_key = f"{event.repository}#{pr_number}"
                if review_key in self.active_reviews:
                    logger.info(f"PR {review_key} 已在审查中, 跳过重复请求")
                    return True

                if self.unified_ai_handler and hasattr(self.unified_ai_handler, "review_code_changes"):
                    mcp_ready = False
                    if hasattr(self.unified_ai_handler, "mcp_tools") and self.unified_ai_handler.mcp_tools:
                        if hasattr(self.unified_ai_handler, "_is_mcp_tools_initialized"):
                            mcp_ready = self.unified_ai_handler._is_mcp_tools_initialized()
                        else:
                            mcp_ready = (
                                hasattr(
                                    self.unified_ai_handler.mcp_tools,
                                    "_initialized",
                                )
                                and self.unified_ai_handler.mcp_tools._initialized
                            )

                    if mcp_ready:
                        self.active_reviews.add(review_key)
                        if len(self.active_reviews) > self.review_cache_max_size:
                            # 移除最旧的一些条目(简单实现)
                            excess = len(self.active_reviews) - self.review_cache_max_size
                            for _ in range(excess):
                                self.active_reviews.pop()

                        asyncio.create_task(self._perform_ai_review(event.repository, pr_number, pr))
                        logger.info(f"🤖 {bot_username} 被请求审核 PR {event.repository}#{pr_number}, 启动审查")
                    else:
                        logger.warning(f"MCP工具未就绪, 无法启动AI审核: {event.repository}#{pr_number}")
                        await self._remove_review_and_comment(
                            owner,
                            repo,
                            pr_number,
                            bot_username,
                            "🚫 AI审查工具暂时不可用, 请稍后重试或联系管理员",
                        )
                else:
                    await self._remove_review_and_comment(
                        owner,
                        repo,
                        pr_number,
                        bot_username,
                        "🚫 本仓库未允许AI审查功能",
                    )
            elif action == "review_requested" and not bot_requested:
                pass
            elif action == "review_request_removed" and bot_username in event.payload.get("requested_reviewer", {}).get(
                "login", ""
            ):
                logger.info(f"{bot_username} 的审核请求已被移除: {event.repository}#{pr_number}")
            return True

        except Exception as e:
            logger.error(f"处理审核请求异常: {e}")
            return False

    async def _remove_review_and_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        bot_username: str,
        comment_text: str,
    ):
        """移除审核请求并添加评论"""
        try:
            api_client = self.github_processor._get_api_client(f"{owner}/{repo}")
            if not api_client:
                return
            await self._check_and_hide_outdated_reviews(api_client, owner, repo, pr_number, bot_username)
            keywords = ["Github Bot", "baiyao105"]
            existing_comment = await api_client.find_bot_comment_by_keywords(
                owner, repo, pr_number, keywords, bot_username
            )
            if existing_comment:
                comment_id = existing_comment.get("id")
                if comment_id:
                    await api_client.update_issue_comment(owner, repo, comment_id, comment_text)
                    logger.success(f"已更新 PR {owner}/{repo}#{pr_number} 的评论: {comment_text}")
                else:
                    await api_client.create_issue_comment(owner, repo, pr_number, comment_text)
                    logger.success(f"已评论 PR {owner}/{repo}#{pr_number}: {comment_text}")
            else:
                await api_client.create_issue_comment(owner, repo, pr_number, comment_text)
                logger.success(f"已评论 PR {owner}/{repo}#{pr_number}: {comment_text}")
            await api_client.remove_review_request(owner, repo, pr_number, [bot_username])
            logger.success(f"已移除 {bot_username} 的审核请求: {owner}/{repo}#{pr_number}")
        except Exception as e:
            logger.error(f"移除审核请求和评论异常: {e}")

    async def _check_and_hide_outdated_reviews(
        self, api_client, owner: str, repo: str, pr_number: int, bot_username: str
    ):
        """检查并隐藏过时的审查结果"""
        try:
            reviews = await api_client.get_pr_reviews(owner, repo, pr_number)
            for review in reviews:
                review_author = review.get("user", {}).get("login", "")
                review_state = review.get("state", "")
                review_id = review.get("id")
                if review_author == bot_username and review_state in ["CHANGES_REQUESTED", "COMMENTED"] and review_id:
                    await api_client.hide_review_as_outdated(owner, repo, review_id)
                    logger.debug(f"隐藏了过时的审查结果: {owner}/{repo}#{pr_number} review#{review_id}")
        except Exception as e:
            logger.error(f"检查和隐藏过时审查异常: {e}")

    async def _perform_ai_review(self, repository: str, pr_number: int, pr_data: Dict[str, Any]):
        """执行智能代码审查"""
        review_key = f"{repository}#{pr_number}"
        try:
            logger.info(f"🔍 开始智能代码审查: {repository}#{pr_number}")
            owner, repo = repository.split("/")
            api_client = self.github_processor._get_api_client(repository)
            if not api_client:
                logger.error(f"❌ 无法获取GitHub API客户端: {repository}")
                return

            # 获取PR详细信息
            pr_files = await api_client.get_pr_files(owner, repo, pr_number)
            if not pr_files:
                logger.warning(f"⚠️ 未获取到PR文件变更: {repository}#{pr_number}")
                repo_config = self.config_manager.get_repository_config(repository)
                bot_username = repo_config.get("allow_review", {}).get("bot_username", "")
                await self._remove_review_and_comment(owner, repo, pr_number, bot_username, "📝 无法获取PR文件变更信息")
                return
            pr_context = {
                "pull_request": pr_data,
                "files": pr_files,
                "repository": {"full_name": repository},
            }

            review_result = await self.unified_ai_handler.review_code_changes(
                pull_request=pr_data, repository={"full_name": repository}
            )

            if review_result:
                summary = review_result.get("summary", "") if isinstance(review_result, dict) else getattr(review_result, "summary", "")
                if "审查异常" in str(summary) or "error" in str(summary).lower():
                    logger.error(f"审查处理异常: {repository}#{pr_number}")
                    repo_config = self.config_manager.get_repository_config(repository)
                    bot_username = repo_config.get("allow_review", {}).get("bot_username", "")
                    await self._remove_review_and_comment(
                        owner,
                        repo,
                        pr_number,
                        bot_username,
                        f"""审查遇到了一些问题呢

> [!CAUTION]
> 🔧 **错误信息**: {summary}


---
✨ Powered by **baiyao105**' GitHub Bot""",
                    )
                    await api_client.remove_review_request(owner, repo, pr_number, [bot_username])
                    return

                # 提交审核结果
                success = await self.github_processor.submit_ai_review(repository, pr_number, review_result)
                if success:
                    logger.info(f"审查完成并提交: {repository}#{pr_number}")
                    if self.msg_processor:
                        try:
                            from .msg_req import MessageType
                            if isinstance(review_result, dict):
                                review_data = {
                                    "overall_score": review_result.get("overall_score", 85),
                                    "approved": review_result.get("approved", True),
                                    "summary": review_result.get("summary", review_result.get("review_content", "AI审查完成")),
                                    "issues_count": review_result.get("issues_count", {})
                                }
                            else:
                                review_data = {
                                    "overall_score": getattr(review_result, "overall_score", 85),
                                    "approved": getattr(review_result, "approved", True),
                                    "summary": getattr(review_result, "summary", getattr(review_result, "review_content", "AI审查完成")),
                                    "issues_count": getattr(review_result, "issues_count", {})
                                }
                            ai_review_payload = {
                                "repository": {"full_name": repository},
                                "pull_request": pr_data,
                                "review_result": review_data
                            }
                            message_request = self.msg_processor.create_message_request(
                                MessageType.AI_REVIEW, ai_review_payload, repository
                            )
                            if message_request:
                                await self.msg_processor.process_message_request(message_request)
                                logger.info(f"AI审查消息通知已发送: {repository}#{pr_number}")
                            else:
                                logger.warning(f"AI审查消息请求创建失败: {repository}#{pr_number}")
                        except Exception as msg_error:
                            logger.error(f"发送AI审查消息通知异常: {msg_error}")
                else:
                    logger.error(f"审查结果提交失败: {repository}#{pr_number}")
                    # 提交失败时也要移除审核请求
                    repo_config = self.config_manager.get_repository_config(repository)
                    bot_username = repo_config.get("allow_review", {}).get("bot_username", "")
                    await self._remove_review_and_comment(owner, repo, pr_number, bot_username, "审查结果提交失败")
            else:
                logger.warning(f"审查未产生有效结果: {repository}#{pr_number}")
                repo_config = self.config_manager.get_repository_config(repository)
                bot_username = repo_config.get("allow_review", {}).get("bot_username", "")
                if bot_username:
                    await self._remove_review_and_comment(
                        owner,
                        repo,
                        pr_number,
                        bot_username,
                        """审查暂时无法处理此PR

💡 **原因**:
- 审查未产生有效结果

---
✨ Powered by **baiyao105**' GitHub Bot""",
                    )
                    await api_client.remove_review_request(owner, repo, pr_number, [bot_username])

        except Exception as e:
            logger.error(f"代码审查异常: {repository}#{pr_number} - {e}")
            try:
                owner, repo = repository.split("/")
                repo_config = self.config_manager.get_repository_config(repository)
                bot_username = repo_config.get("allow_review", {}).get("bot_username", "")

                if bot_username:
                    await self._remove_review_and_comment(
                        owner,
                        repo,
                        pr_number,
                        bot_username,
                        f"""审查过程中发生异常

> [!CAUTION]
> 🔧 **错误信息**: {str(e)}

---
✨ Powered by **baiyao105**' GitHub Bot""",
                    )
                    api_client = self.github_processor._get_api_client(repository)
                    if api_client:
                        await api_client.remove_review_request(owner, repo, pr_number, [bot_username])
            except Exception as cleanup_error:
                logger.error(f"清理审查请求时异常: {cleanup_error}")
        finally:
            # 无论成功还是失败都要从活跃审查集合中移除
            self.active_reviews.discard(review_key)
            logger.debug(f"已从活跃审查集合中移除: {review_key}")

    def get_stats(self) -> Dict[str, Any]:
        """获取处理统计信息"""
        current_time = time.time()
        uptime = current_time - self.last_reset_time
        return {
            "uptime_seconds": uptime,
            "queue_size": self.event_queue.qsize(),
            "is_processing": self.is_processing,
            "event_stats": dict(self.event_stats),
            "total_events": sum(self.event_stats.values()),
            "delivery_cache_size": len(self.delivery_cache),
            "supported_events": list(self.supported_events),
        }

    def reset_stats(self):
        """重置统计信息"""
        self.event_stats.clear()
        self.last_reset_time = time.time()
        logger.success("统计信息已重置")

    def clear_delivery_cache(self):
        """清理投递缓存"""
        self.delivery_cache.clear()
        logger.success("投递缓存已清理")

    async def cleanup(self):
        """清理资源"""
        await self.stop_processing()
        self.delivery_cache.clear()
        self.event_stats.clear()
        while not self.event_queue.empty():
            try:
                self.event_queue.get_nowait()
                self.event_queue.task_done()
            except asyncio.QueueEmpty:
                break

        logger.success("处理器已清理")


# 全局Webhook处理器实例
_webhook_processor = None


def get_webhook_processor(config_manager) -> WebhookProcessor:
    """获取全局Webhook处理器实例"""
    global _webhook_processor
    if _webhook_processor is None:
        _webhook_processor = WebhookProcessor(config_manager)
    return _webhook_processor


async def cleanup_webhook_processor():
    """清理Webhook处理器资源"""
    global _webhook_processor
    if _webhook_processor:
        await _webhook_processor.cleanup()
        _webhook_processor = None
