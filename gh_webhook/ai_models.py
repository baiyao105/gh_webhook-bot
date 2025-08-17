"""
ai数据类
"""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from loguru import logger


class ContextType(Enum):
    """上下文类型"""

    QQ_GROUP = "qq_group"
    QQ_PRIVATE = "qq_private"
    GITHUB_PR = "github_pr"
    GITHUB_PR_REVIEW = "github_pr_review"
    GITHUB_ISSUE = "github_issue"
    GITHUB_COMMENT = "github_comment"
    GENERAL = "general"


class ToolCallStatus(Enum):
    """工具调用状态"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class Message:
    """消息数据结构"""

    role: str  # user, ai, system
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    author: Optional[str] = None
    message_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "author": self.author,
            "message_id": self.message_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """从字典创建消息"""
        timestamp_str = data.get("timestamp")
        if isinstance(timestamp_str, str):
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
            except ValueError:
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            timestamp=timestamp,
            author=data.get("author"),
            message_id=data.get("message_id"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ToolCall:
    """工具调用信息"""

    name: str
    parameters: Dict[str, Any]
    call_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    status: ToolCallStatus = ToolCallStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 2

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "parameters": self.parameters,
            "call_id": self.call_id,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "execution_time": self.execution_time,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolCall":
        """从字典创建工具调用"""
        timestamp_str = data.get("timestamp")
        if isinstance(timestamp_str, str):
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
            except ValueError:
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        status_str = data.get("status", "pending")
        try:
            status = ToolCallStatus(status_str)
        except ValueError:
            status = ToolCallStatus.PENDING

        return cls(
            name=data.get("name", ""),
            parameters=data.get("parameters", {}),
            call_id=data.get("call_id", ""),
            timestamp=timestamp,
            status=status,
            result=data.get("result"),
            error=data.get("error"),
            execution_time=data.get("execution_time"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 2),
        )


@dataclass
class ConversationContext:
    """对话上下文"""

    context_id: str
    context_type: ContextType
    messages: List[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # 特定上下文字段
    group_id: Optional[str] = None
    user_id: Optional[str] = None
    repository: Optional[str] = None
    issue_or_pr_id: Optional[str] = None
    max_messages: int = 100

    def add_message(self, message: Message):
        """添加消息到上下文"""
        self.messages.append(message)
        self.last_activity = datetime.now()
        if len(self.messages) > self.max_messages:
            # 保留最近的消息，但保留第一条系统消息(如果有)
            system_messages = [msg for msg in self.messages[:5] if msg.role == "system"]
            recent_messages = self.messages[-(self.max_messages - len(system_messages)) :]
            self.messages = system_messages + recent_messages

    def get_recent_messages(self, limit: int = 10) -> List[Message]:
        """获取最近的消息"""
        return self.messages[-limit:] if self.messages else []

    def get_message_count(self) -> int:
        """获取消息数量"""
        return len(self.messages)

    def get_context_summary(self) -> str:
        """获取上下文摘要"""
        if not self.messages:
            return "暂无对话历史"

        recent = self.get_recent_messages(5)
        summary_parts = []

        for msg in recent:
            author_info = f"({msg.author})" if msg.author and msg.role == "user" else ""
            role_name = {"user": "用户", "assistant": "助手", "system": "系统"}.get(msg.role, msg.role)
            content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
            summary_parts.append(f"{role_name}{author_info}: {content}")

        return "\n".join(summary_parts)

    def is_expired(self, max_age_hours: int = 24) -> bool:
        """检查上下文是否过期"""
        age = datetime.now() - self.last_activity
        return age.total_seconds() > (max_age_hours * 3600)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "context_id": self.context_id,
            "context_type": self.context_type.value,
            "messages": [msg.to_dict() for msg in self.messages],
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "metadata": self.metadata,
            "group_id": self.group_id,
            "user_id": self.user_id,
            "repository": self.repository,
            "issue_or_pr_id": self.issue_or_pr_id,
            "max_messages": self.max_messages,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationContext":
        """从字典创建上下文"""
        created_at_str = data.get("created_at")
        if isinstance(created_at_str, str):
            try:
                created_at = datetime.fromisoformat(created_at_str)
            except ValueError:
                created_at = datetime.now()
        else:
            created_at = datetime.now()

        last_activity_str = data.get("last_activity")
        if isinstance(last_activity_str, str):
            try:
                last_activity = datetime.fromisoformat(last_activity_str)
            except ValueError:
                last_activity = datetime.now()
        else:
            last_activity = datetime.now()
        context_type_str = data.get("context_type", "general")
        try:
            context_type = ContextType(context_type_str)
        except ValueError:
            context_type = ContextType.GENERAL
        messages_data = data.get("messages", [])
        messages = [Message.from_dict(msg_data) for msg_data in messages_data]

        return cls(
            context_id=data.get("context_id", ""),
            context_type=context_type,
            messages=messages,
            created_at=created_at,
            last_activity=last_activity,
            metadata=data.get("metadata", {}),
            group_id=data.get("group_id"),
            user_id=data.get("user_id"),
            repository=data.get("repository"),
            issue_or_pr_id=data.get("issue_or_pr_id"),
            max_messages=data.get("max_messages", 100),
        )


@dataclass
class MultiTurnSession:
    """多轮对话会话"""

    session_id: str
    context: ConversationContext
    tool_calls: List[ToolCall] = field(default_factory=list)
    max_turns: int = 5
    current_turn: int = 0
    allow_early_finish: bool = True
    session_data: Dict[str, Any] = field(default_factory=dict)

    def add_tool_call(self, tool_call: ToolCall):
        """添加工具调用"""
        self.tool_calls.append(tool_call)
        self.context.last_activity = datetime.now()

    def get_successful_tool_calls(self) -> List[ToolCall]:
        """获取成功的工具调用"""
        return [tc for tc in self.tool_calls if tc.status == ToolCallStatus.SUCCESS]

    def get_failed_tool_calls(self) -> List[ToolCall]:
        """获取失败的工具调用"""
        return [tc for tc in self.tool_calls if tc.status == ToolCallStatus.FAILED]

    def is_max_turns_reached(self) -> bool:
        """检查是否达到最大轮数"""
        return self.current_turn >= self.max_turns

    def increment_turn(self):
        """增加轮数"""
        self.current_turn += 1

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "context": self.context.to_dict(),
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "max_turns": self.max_turns,
            "current_turn": self.current_turn,
            "allow_early_finish": self.allow_early_finish,
            "session_data": self.session_data,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MultiTurnSession":
        """从字典创建会话"""
        context_data = data.get("context", {})
        context = ConversationContext.from_dict(context_data)
        tool_calls_data = data.get("tool_calls", [])
        tool_calls = [ToolCall.from_dict(tc_data) for tc_data in tool_calls_data]

        return cls(
            session_id=data.get("session_id", ""),
            context=context,
            tool_calls=tool_calls,
            max_turns=data.get("max_turns", 5),
            current_turn=data.get("current_turn", 0),
            allow_early_finish=data.get("allow_early_finish", True),
            session_data=data.get("session_data", {}),
        )


@dataclass
class RateLimitInfo:
    """限流信息"""

    user_id: str
    request_count: int = 0
    last_request: datetime = field(default_factory=datetime.now)
    window_start: datetime = field(default_factory=datetime.now)
    blocked_until: Optional[datetime] = None

    def is_blocked(self) -> bool:
        """检查是否被阻止"""
        if self.blocked_until is None:
            return False
        return datetime.now() < self.blocked_until

    def reset_if_needed(self, window_seconds: int = 3600):
        """如果需要则重置计数器"""
        now = datetime.now()
        if (now - self.window_start).total_seconds() >= window_seconds:
            self.request_count = 0
            self.window_start = now

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "user_id": self.user_id,
            "request_count": self.request_count,
            "last_request": self.last_request.isoformat(),
            "window_start": self.window_start.isoformat(),
            "blocked_until": (self.blocked_until.isoformat() if self.blocked_until else None),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RateLimitInfo":
        """从字典创建限流信息"""
        # 解析时间戳
        last_request_str = data.get("last_request")
        if isinstance(last_request_str, str):
            try:
                last_request = datetime.fromisoformat(last_request_str)
            except ValueError:
                last_request = datetime.now()
        else:
            last_request = datetime.now()

        window_start_str = data.get("window_start")
        if isinstance(window_start_str, str):
            try:
                window_start = datetime.fromisoformat(window_start_str)
            except ValueError:
                window_start = datetime.now()
        else:
            window_start = datetime.now()

        blocked_until_str = data.get("blocked_until")
        blocked_until = None
        if isinstance(blocked_until_str, str):
            try:
                blocked_until = datetime.fromisoformat(blocked_until_str)
            except ValueError:
                pass
        return cls(
            user_id=data.get("user_id", ""),
            request_count=data.get("request_count", 0),
            last_request=last_request,
            window_start=window_start,
            blocked_until=blocked_until,
        )


class ContextManager:
    """上下文管理器"""

    def __init__(self, storage_path: str, max_contexts: int = 1000):
        self.storage_path = Path(storage_path)
        self.max_contexts = max_contexts
        self.contexts: Dict[str, ConversationContext] = {}
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._load_contexts()

    def _load_contexts(self):
        """加载现有上下文"""
        try:
            context_files = list(self.storage_path.glob("*.json"))
            loaded_count = 0
            for context_file in context_files:
                try:
                    with open(context_file, "r", encoding="utf-8") as f:
                        context_data = json.load(f)

                    context = ConversationContext.from_dict(context_data)
                    if not context.is_expired(72):  # 72小时过期
                        self.contexts[context.context_id] = context
                        loaded_count += 1
                    else:
                        context_file.unlink()
                except Exception as e:
                    logger.warning(f"加载上下文失败 {context_file}: {e}")
                    continue

            logger.success(f"加载了 {loaded_count} 个上下文")
        except Exception as e:
            logger.error(f"加载上下文异常: {e}")

    def get_context(self, context_id: str) -> Optional[ConversationContext]:
        """获取已存在的上下文，不存在则返回None"""
        if context_id in self.contexts:
            context = self.contexts[context_id]
            context.last_activity = datetime.now()
            return context
        return None

    def get_or_create_context(self, context_id: str, context_type: ContextType, **kwargs) -> ConversationContext:
        """获取或创建上下文"""
        if context_id in self.contexts:
            context = self.contexts[context_id]
            context.last_activity = datetime.now()
            return context
        context = ConversationContext(context_id=context_id, context_type=context_type, **kwargs)

        self.contexts[context_id] = context
        if len(self.contexts) > self.max_contexts:
            self._cleanup_old_contexts()

        logger.info(f"创建新上下文: {context_id} (类型: {context_type.value})")
        return context

    def save_context(self, context: ConversationContext):
        """保存上下文到文件"""
        try:
            context_file = self.storage_path / f"{context.context_id}.json"

            with open(context_file, "w", encoding="utf-8") as f:
                json.dump(context.to_dict(), f, ensure_ascii=False, indent=2)
            # logger.debug(f"保存上下文: {context.context_id}")
        except Exception as e:
            logger.error(f"保存上下文失败 {context.context_id}: {e}")

    def delete_context(self, context_id: str):
        """删除上下文"""
        try:
            if context_id in self.contexts:
                del self.contexts[context_id]

            context_file = self.storage_path / f"{context_id}.json"
            if context_file.exists():
                context_file.unlink()
            logger.debug(f"删除上下文: {context_id}")
        except Exception as e:
            logger.error(f"删除上下文失败 {context_id}: {e}")

    def cleanup_expired_contexts(self, max_age_hours: int = 24):
        """清理过期上下文"""
        try:
            expired_contexts = []

            for context_id, context in self.contexts.items():
                if context.is_expired(max_age_hours):
                    expired_contexts.append(context_id)
            for context_id in expired_contexts:
                self.delete_context(context_id)
            if expired_contexts:
                logger.debug(f"清理了 {len(expired_contexts)} 个过期上下文")

        except Exception as e:
            logger.error(f"清理过期上下文异常: {e}")

    def _cleanup_old_contexts(self):
        """清理最旧的上下文"""
        try:
            sorted_contexts = sorted(self.contexts.items(), key=lambda x: x[1].last_activity)
            excess_count = len(self.contexts) - self.max_contexts + 100  # 留出缓冲
            for i in range(min(excess_count, len(sorted_contexts))):
                context_id = sorted_contexts[i][0]
                self.delete_context(context_id)
            logger.debug(f"清理了 {excess_count} 个最旧的上下文")

        except Exception as e:
            logger.error(f"清理最旧上下文异常: {e}")

    def get_context_stats(self) -> Dict[str, Any]:
        """获取上下文统计信息"""
        stats = {
            "total_contexts": len(self.contexts),
            "context_types": {},
            "message_counts": {"total": 0, "by_type": {}},
            "active_contexts_24h": 0,
            "storage_path": str(self.storage_path),
        }

        now = datetime.now()
        for context in self.contexts.values():
            context_type = context.context_type.value
            stats["context_types"][context_type] = stats["context_types"].get(context_type, 0) + 1
            message_count = context.get_message_count()
            stats["message_counts"]["total"] += message_count
            stats["message_counts"]["by_type"][context_type] = (
                stats["message_counts"]["by_type"].get(context_type, 0) + message_count
            )
            if (now - context.last_activity).total_seconds() < 86400:
                stats["active_contexts_24h"] += 1

        return stats

    def search_contexts(
        self,
        query: str,
        context_types: Optional[List[ContextType]] = None,
        limit: int = 10,
    ) -> List[ConversationContext]:
        """搜索上下文"""
        results = []
        query_lower = query.lower()

        for context in self.contexts.values():
            if context_types and context.context_type not in context_types:
                continue
            for message in context.messages:  # 搜消息内容
                if query_lower in message.content.lower():
                    results.append(context)
                    break
            if context.repository and query_lower in context.repository.lower():  # 搜元数据
                if context not in results:
                    results.append(context)
            if len(results) >= limit:
                break
        results.sort(key=lambda x: x.last_activity, reverse=True)  # 最后活跃时间排序

        return results[:limit]
