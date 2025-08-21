"""
AI处理器
"""

import asyncio
import json
import re
import time
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from loguru import logger
from openai import AsyncOpenAI

from .permission_manager import get_permission_manager
from .ai_models import (
    ConversationContext,
    Message,
    ToolCall,
    ContextType,
    ToolCallStatus,
    ContextManager,
    RateLimitInfo,
)
from .prompt_engine import get_prompt_manager
from .mcp import MCPTools, get_ai_message_parser, get_unified_ai_mcp_interface
from .conf import get_config_manager


class SecurityValidator:
    """一些安全验证"""

    TOOL_PARAM_WHITELIST = {
        "get_repository_info": {"owner", "repo", "include_stats"},
        "list_pull_requests": {
            "owner",
            "repo",
            "state",
            "sort",
            "direction",
            "per_page",
        },
        "get_pull_request": {"owner", "repo", "pr_number"},
        "list_issues": {
            "owner",
            "repo",
            "state",
            "labels",
            "sort",
            "direction",
            "per_page",
        },
        "get_issue": {"owner", "repo", "issue_number"},
        "create_comment": {"owner", "repo", "issue_number", "body"},
        "search_repositories": {"q", "sort", "order", "per_page"},
        "get_user_info": {"username"},
        "search_conversations": {
            "query",
            "context_types",
            "repositories",
            "users",
            "limit",
        },
        "get_context_stats": {},
        "find_related_contexts": {"context_id", "similarity_threshold"},
        "export_context": {"context_id", "format"},
    }
    DANGEROUS_PATTERNS = [
        r"\.\./",
        r"<script",
        r"javascript:",
        r"eval\(",
        r"exec\(",
        r"__import__",
        r"subprocess",
        r"os\.",
    ]

    @classmethod
    def validate_tool_call(cls, tool_name: str, parameters: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """验证工具调用的安全性"""
        if tool_name not in cls.TOOL_PARAM_WHITELIST:
            return False, f"未授权的工具: {tool_name}"
        allowed_params = cls.TOOL_PARAM_WHITELIST[tool_name]
        for param_name in parameters.keys():
            if param_name not in allowed_params:
                return False, f"未授权的参数: {param_name} (工具: {tool_name})"
        for param_name, param_value in parameters.items():
            if isinstance(param_value, str):
                for pattern in cls.DANGEROUS_PATTERNS:
                    if re.search(pattern, param_value, re.IGNORECASE):
                        return False, f"参数包含危险内容: {param_name}"

        return True, None

    @classmethod
    def sanitize_parameters(cls, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """清理和过滤参数"""
        if tool_name not in cls.TOOL_PARAM_WHITELIST:
            return {}
        allowed_params = cls.TOOL_PARAM_WHITELIST[tool_name]
        sanitized = {}
        for param_name, param_value in parameters.items():
            if param_name in allowed_params:
                if isinstance(param_value, str):
                    param_value = re.sub(r'[<>"\'\\\/]', "", param_value)
                    param_value = param_value[:1000]
                sanitized[param_name] = param_value

        return sanitized


class RateLimiter:
    """限流器"""

    def __init__(self):
        self.user_limits: Dict[str, RateLimitInfo] = {}
        self.global_limits = {
            "requests_per_hour": 100,
            "requests_per_minute": 10,
            "ai_calls_per_hour": 50,
            "tool_calls_per_hour": 30,
        }

    def check_rate_limit(self, user_id: str, operation_type: str = "request") -> Tuple[bool, Optional[str]]:
        """检查是否超过限流"""
        now = datetime.now()

        if user_id not in self.user_limits:
            self.user_limits[user_id] = RateLimitInfo(user_id=user_id)

        user_limit = self.user_limits[user_id]
        if user_limit.is_blocked():
            remaining_time = (user_limit.blocked_until - now).total_seconds()
            return False, f"限流中,剩余时间: {int(remaining_time)}秒"
        user_limit.reset_if_needed(3600)  # 1小时窗口
        limit_key = f"{operation_type}s_per_hour"
        max_requests = self.global_limits.get(limit_key, 100)
        if user_limit.request_count >= max_requests:
            user_limit.blocked_until = now + timedelta(hours=1)
            return False, f"超过{operation_type}限制 ({max_requests}/小时)"
        user_limit.request_count += 1
        user_limit.last_request = now

        return True, None

    def cleanup_expired_limits(self):
        """清理过期限流"""
        now = datetime.now()
        expired_users = []

        for user_id, limit_info in self.user_limits.items():
            if (now - limit_info.last_request).total_seconds() > 86400:
                expired_users.append(user_id)

        for user_id in expired_users:
            del self.user_limits[user_id]


class EnhancedAIHandler:
    """增强的AI处理器"""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.initialized = False
        self.permission_manager = None
        self.context_manager = None
        self.prompt_manager = None
        self.mcp_tools = None
        self.ai_message_parser = None
        self.unified_ai_mcp_interface = None
        self.ai_client = None  # ai
        self.security_validator = SecurityValidator()
        self.rate_limiter = RateLimiter()  # 限流
        self.github_processor = None  # 依赖
        self.max_contexts = 1000
        self.context_max_age = 86400  # 24小时
        self.max_message_length = 4000
        self.max_tool_calls_per_session = 10

        self.stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "tool_calls": 0,
            "contexts_created": 0,
            "rate_limited_requests": 0,
        }

    async def initialize(self) -> bool:
        """初始化处理器"""
        try:
            self.permission_manager = get_permission_manager()
            if not self.permission_manager:
                logger.error("权限管理器初始化失败")
                return False

            await self._initialize_ai_client()
            storage_path = Path(self.config_manager.get("ai_handler.storage_path", "./ai_contexts"))
            self.context_manager = ContextManager(str(storage_path), self.max_contexts)
            # 提示词管理
            prompts_path = Path(__file__).parent / "prompts"
            self.prompt_manager = get_prompt_manager(str(prompts_path))
            # MCP工具
            if not hasattr(self, "mcp_tools") or not self.mcp_tools:
                self.mcp_tools = MCPTools(self.config_manager, self.context_manager, "ai_handler")
                logger.success("创建新的MCP工具实例")
            self.ai_message_parser = get_ai_message_parser(self.config_manager, self.context_manager)
            if not self.ai_message_parser:
                logger.error("AI消息解析器初始化失败")
                return False
            self.unified_ai_mcp_interface = get_unified_ai_mcp_interface(self.config_manager, self.context_manager)
            if not self.unified_ai_mcp_interface:
                logger.error("统一MCP接口初始化失败")
                return False

            self.initialized = True
            return True

        except Exception as e:
            logger.error(f"初始化处理器失败: {e}")
            return False

    def set_dependencies(self, github_processor, **kwargs):
        """设置依赖组件"""
        self.github_processor = github_processor
        if "mcp_tools" in kwargs:  # 设置MCP工具
            self.mcp_tools = kwargs["mcp_tools"]

    async def _initialize_ai_client(self):
        """初始化客户端"""
        try:
            ai_config = self.config_manager.get_ai_config()
            if not ai_config.get("enabled", False):
                return
            api_key = ai_config.get("api_key", "")
            base_url = ai_config.get("base_url", "https://api.siliconflow.cn/v1")
            if not api_key:
                return
            # 创建OpenAI客户端
            self.ai_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        except Exception as e:
            logger.error(f"客户端初始化失败: {e}")
            self.ai_client = None

    def _is_mcp_tools_initialized(self) -> bool:
        """检查工具是否已初始化"""
        if not hasattr(self, "mcp_tools") or not self.mcp_tools:
            logger.debug("MCP未设置或为空")
            return False

        if hasattr(self.mcp_tools, "_initialized"):
            initialized = getattr(self.mcp_tools, "_initialized", False)
            logger.debug(f"MCP工具初始化状态: {initialized}")
            return initialized
        else:
            logger.debug("MCP工具没有_initialized属性")
            return False

    def _generate_context_id(self, context_type: ContextType, **kwargs) -> str:
        """生成上下文ID"""
        if context_type == ContextType.QQ_GROUP:
            group_id = kwargs.get("group_id", "")
            user_id = kwargs.get("user_id", "")
            return f"qq_group_{group_id}_{user_id}"
        elif context_type == ContextType.QQ_PRIVATE:
            user_id = kwargs.get("user_id", "")
            return f"qq_private_{user_id}"
        elif context_type == ContextType.GITHUB_PR:
            repository = kwargs.get("repository", "").replace("/", "_")
            pr_id = kwargs.get("pr_id", "")
            return f"github_pr_{repository}_{pr_id}"
        elif context_type == ContextType.GITHUB_ISSUE:
            repository = kwargs.get("repository", "").replace("/", "_")
            issue_id = kwargs.get("issue_id", "")
            return f"github_issue_{repository}_{issue_id}"
        else:
            content = json.dumps(kwargs, sort_keys=True)
            return f"{context_type.value}_{hashlib.md5(content.encode()).hexdigest()[:8]}"  # UUID(迫真

    async def handle_qq_message(self, context: Dict[str, Any]) -> str:
        """处理QQ消息"""
        try:
            self.stats["total_requests"] += 1
            if not self.initialized:
                await self.initialize()

            user_id = context.get("user_id")
            group_id = context.get("group_id")
            content = context.get("content", "")
            if not user_id or not content:
                return "消息信息不完整"

            # 一些检查
            rate_ok, rate_msg = self.rate_limiter.check_rate_limit(user_id, "request")
            if not rate_ok:
                self.stats["rate_limited_requests"] += 1
                return f"请求过于频繁, 请稍后再试\n{rate_msg}"
            if len(content) > self.max_message_length:
                return f"消息过长, 请控制在{self.max_message_length}字符以内"
            context_type = ContextType.QQ_GROUP if group_id else ContextType.QQ_PRIVATE
            context_id = self._generate_context_id(context_type, group_id=group_id, user_id=user_id)
            conv_context = self.context_manager.get_or_create_context(
                context_id=context_id,
                context_type=context_type,
                group_id=group_id or "",
                user_id=user_id,
            )

            # 获取用户权限信息
            user_info = self.permission_manager.get_user_info(user_id)
            github_username = user_info.get("github_username") if user_info else None
            # 从获取权限列表
            qq_perm = self.permission_manager.get_qq_permission(user_id)
            github_perm = self.permission_manager.get_github_permission(user_id)
            user_permissions = []
            if qq_perm and qq_perm.name != "NONE":
                user_permissions.append(f"qq_{qq_perm.name.lower()}")
            if github_perm and github_perm.name != "NONE":
                user_permissions.append(f"github_{github_perm.name.lower()}")
            user_message_id = context.get("message_id", "")
            user_message = Message(
                role="user",
                content=content,
                author=user_id,
                message_id=user_message_id,
            )
            conv_context.add_message(user_message)
            ai_response = await self._generate_ai_response(
                conv_context, content, user_id, github_username, user_permissions
            )
            ai_message = Message(
                role="assistant",
                content=ai_response,
                metadata={"reply_to_message_id": user_message_id} if user_message_id else None
            )
            conv_context.add_message(ai_message)
            self.context_manager.save_context(conv_context)

            self.stats["successful_requests"] += 1
            return ai_response

        except Exception as e:
            self.stats["failed_requests"] += 1
            logger.error(f"处理QQ消息异常: {e}")
            return f"处理消息时出现错误, 请稍后再试\n错误信息: {str(e)}"

    async def _generate_ai_response(
        self,
        context: ConversationContext,
        current_message: str,
        user_id: str,
        github_username: Optional[str],
        user_permissions: List[str],
    ) -> str:
        """生成AI回复"""
        try:
            rate_ok, rate_msg = self.rate_limiter.check_rate_limit(user_id, "ai_call")
            if not rate_ok:
                return f"AI调用过于频繁, 请稍后再试\n{rate_msg}"
            system_prompt = self.prompt_manager.get_prompt_for_context(
                context,
                user_name=user_id,
                github_username=github_username,
                user_permission=(", ".join(user_permissions) if user_permissions else "无特殊权限"),
                available_tools=self._get_available_tools_for_user(user_permissions),
            )
            tool_calls = getattr(context, 'tool_calls', []) or []
            # 构建完整的提示词
            full_prompt = self._build_full_prompt(system_prompt, context, current_message, tool_calls)
            response = await self._call_ai_model(full_prompt, context, user_id, github_username, user_permissions)

            return response

        except Exception as e:
            logger.error(f"生成AI回复异常: {e}")
            return f"生成回复时出现错误\n请稍后再试~"

    def _get_available_tools_for_user(self, user_permissions: List[str]) -> List[Dict[str, Any]]:
        """获取可用的工具列表"""
        available_tools = []
        if hasattr(self, "mcp_tools") and self.mcp_tools:
            try:
                mcp_tools_config = self.mcp_tools.get_available_tools()
                logger.debug(f"从MCP获取到 {len(mcp_tools_config)} 个工具定义")

                for tool_name, tool_config in mcp_tools_config.items():
                    available_tools.append(
                        {
                            "name": tool_name,
                            "description": tool_config.get("description", ""),
                            "parameters": tool_config.get("parameters", {}),
                            "required_permissions": tool_config.get("permissions", []),  # 保留权限信息供执行时检查
                        }
                    )
                    category = tool_config.get("category", "unknown")
                    if hasattr(category, "value"):
                        category_str = category.value
                    elif hasattr(category, "name"):
                        category_str = category.name
                    else:
                        category_str = str(category)
                    available_tools[-1]["category"] = category_str

                return available_tools

            except Exception as e:
                logger.error(f"从MCP获取工具失败: {e}")

        return available_tools

    async def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], user_id: str) -> Optional[ToolCall]:
        """执行单个工具调用"""
        try:
            # 安全验证
            is_valid, error_msg = self.security_validator.validate_tool_call(tool_name, parameters)
            if not is_valid:
                logger.warning(f"工具调用安全验证失败: {error_msg}")
                return ToolCall(
                    name=tool_name,
                    parameters=parameters,
                    call_id=f"{tool_name}_{int(time.time())}",
                    error=error_msg,
                    status=ToolCallStatus.FAILED,
                )
            # 清理参数
            clean_params = self.security_validator.sanitize_parameters(tool_name, parameters)
            # 创建工具调用记录
            tool_call = ToolCall(
                name=tool_name,
                parameters=clean_params,
                call_id=f"{tool_name}_{int(time.time())}_{user_id}",
                status=ToolCallStatus.RUNNING,
            )
            start_time = time.time()
            if self._is_mcp_tools_initialized():
                result = await self._call_mcp_tool(tool_name, clean_params)
            else:
                logger.warning(f"MCP未初始化")

            tool_call.execution_time = time.time() - start_time
            if result and result.get("success", False):
                tool_call.result = result
                tool_call.status = ToolCallStatus.SUCCESS
            else:
                tool_call.error = result.get("error", "工具调用失败") if result else "工具调用失败"
                tool_call.status = ToolCallStatus.FAILED

            return tool_call

        except Exception as e:
            logger.error(f"执行工具 {tool_name} 异常: {e}")
            return ToolCall(
                name=tool_name,
                parameters=parameters,
                call_id=f"{tool_name}_{int(time.time())}",
                error=str(e),
                status=ToolCallStatus.FAILED,
            )

    async def _call_mcp_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """调用MCP"""
        try:
            if not hasattr(self, "mcp_tools") or not self.mcp_tools:
                return {"success": False, "error": "MCP未初始化"}
            result = await self.mcp_tools.call_tool(tool_name, parameters)
            logger.debug(f"MCP工具调用结果 [tool={tool_name}] [success={result.get('success', False)}]")
            return result

        except Exception as e:
            logger.error(f"MCP工具调用异常 [tool={tool_name}] [error={str(e)}]")
            return {"success": False, "error": str(e)}

    def _build_full_prompt(
        self,
        system_prompt: str,
        context: ConversationContext,
        current_message: str,
        tool_calls: List[ToolCall],
    ) -> str:
        """构建提示词"""
        prompt_parts = [system_prompt]
        if context.messages:
            prompt_parts.append("\n## 对话历史")
            recent_messages = context.get_recent_messages(10)
            for msg in recent_messages[:-1]:  # 排除当前消息
                role_name = {"user": "用户", "assistant": "助手", "system": "系统"}.get(msg.role, msg.role)
                author_info = f"({msg.author})" if msg.author and msg.role == "user" else ""
                prompt_parts.append(f"{role_name}{author_info}: {msg.content}")

        if tool_calls:
            prompt_parts.append("\n## 工具调用结果")
            successful_tools = [tc for tc in tool_calls if tc.status == ToolCallStatus.SUCCESS]
            failed_tools = [tc for tc in tool_calls if tc.status == ToolCallStatus.FAILED]
            running_tools = [tc for tc in tool_calls if tc.status == ToolCallStatus.RUNNING]
            total_tools = len(tool_calls)
            success_count = len(successful_tools)
            prompt_parts.append(f"执行: {success_count}/{total_tools} 个工具成功")

            if successful_tools:
                prompt_parts.append("\n**成功的工具**:")
                for tool_call in successful_tools:
                    execution_time = getattr(tool_call, "execution_time", 0)
                    time_info = f" ({execution_time:.2f}s)" if execution_time > 0 else ""
                    if tool_call.result:
                        result_preview = json.dumps(tool_call.result, ensure_ascii=False)[:200]
                        if len(json.dumps(tool_call.result, ensure_ascii=False)) > 200:
                            result_preview += "..."
                        prompt_parts.append(f"- **{tool_call.name}**{time_info}: {result_preview}")
                    else:
                        prompt_parts.append(f"- **{tool_call.name}**{time_info}: 执行成功")

            if failed_tools:
                prompt_parts.append("\n**失败的工具**:")
                for tool_call in failed_tools:
                    error_msg = tool_call.error or "未知错误"
                    prompt_parts.append(f"- **{tool_call.name}**: {error_msg}")
            if running_tools:
                prompt_parts.append("\n**正在执行的工具**:")  # 什么鬼...
                for tool_call in running_tools:
                    prompt_parts.append(f"- **{tool_call.name}**: 执行中...")

        prompt_parts.append(f"\n## 当前消息\n用户: {current_message}")
        prompt_parts.append("\n## 回复要求")
        prompt_parts.append("请严格遵守以下原则：")
        prompt_parts.append("1. **基于事实**：只基于实际获得的数据回复, 不编造任何信息")
        prompt_parts.append("2. **工具约束**：只能使用明确列出的可用工具, 不得调用其他工具")
        prompt_parts.append("3. **实话实说**：如果无法获取信息或执行操作, 直接说明原因")
        prompt_parts.append("4. **简洁明了**：避免冗余描述和糖衣炮弹式的回复")
        prompt_parts.append("5. **温柔专业**：适当使用颜文字")
        prompt_parts.append("6. **针对性强**：针对用户具体问题给出明确答案")

        return "\n".join(prompt_parts)

    async def _call_ai_model(
        self,
        prompt: str,
        context: ConversationContext,
        user_id: str = None,
        github_username: str = None,
        user_permissions: List[str] = None,
    ) -> str:
        """调用AI模型生成回复"""
        try:
            if self.ai_client:
                return await self._call_real_ai_model(prompt, context, user_id, github_username, user_permissions)
            else:
                return "Boom!"

        except Exception as e:
            logger.error(f"调用AI模型异常: {e}")
            return f"模型被调用时似了(对\n{e}"

    async def _call_real_ai_model(
        self,
        prompt: str,
        context: ConversationContext,
        user_id: str = None,
        github_username: str = None,
        user_permissions: List[str] = None,
    ) -> str:
        """调用真实的AI模型, 支持MCP工具多轮对话"""
        session_id = f"{user_id or 'unknown'}_{int(time.time())}"
        logger.info(f"开始多轮会话 [session_id={session_id}] [user={user_id}] [github={github_username}]")
        try:
            ai_config = self.config_manager.get_ai_config()
            model = ai_config.get("model", "gpt-3.5-turbo")
            max_tokens = ai_config.get("max_tokens", 2000)
            temperature = ai_config.get("temperature", 0.3)
            logger.debug(f"会话配置 [model={model}] [max_tokens={max_tokens}] [temperature={temperature}]")
            max_turns = 15
            current_turn = 0

            messages = self._build_initial_messages(context, prompt)
            # logger.debug(f"初始消息历史 [messages_count={len(messages)}]")

            available_tools = self._get_available_tools_for_user(user_permissions)
            if available_tools:
                tools_description = self._format_tools_for_ai(available_tools)
                messages[0]["content"] += f"\n\n可用工具:\n{tools_description}"
                logger.info(f"提供 {len(available_tools)} 个工具")
            else:
                logger.warning("未获取到任何MCP定义")

            logger.info(f"多轮会话循环开始 [max_turns={max_turns}] [session_id={session_id}]")
            while current_turn < max_turns:
                current_turn += 1
                turn_start_time = time.time()
                logger.debug(f"第{current_turn}轮会话开始 [session_id={session_id}]")
                # logger.debug(
                #     f"发送给API的完整请求内容 [turn={current_turn}] [messages_count={len(messages)}]"
                # )
                # logger.debug(
                #     f"API配置: model={model}, max_tokens={max_tokens}, temperature={temperature}"
                # )

                # for i, msg in enumerate(messages):
                #     logger.debug(
                #         f"消息{i+1} [role={msg['role']}] [length={len(msg['content'])}]"
                #     )
                #     logger.debug(f"内容: {msg['content']}")
                # api_request = {
                #     "model": model,
                #     "messages": messages,
                #     "max_tokens": max_tokens,
                #     "temperature": temperature,
                #     "timeout": 30.0,
                # }
                # logger.debug(
                #     f"完整API请求: {json.dumps(api_request, ensure_ascii=False, indent=2)}"
                # )

                logger.debug(f"调用模型 [model={model}] [turn={current_turn}]")
                response = await self.ai_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=30.0,
                )

                if hasattr(response, "usage") and response.usage:
                    logger.debug(f"Token使用情况: {response.usage}")
                if not response.choices or not response.choices[0].message:
                    logger.warning(f"模型返回空值 [turn={current_turn}] [session_id={session_id}]")
                    logger.warning(f"响应choices: {response.choices if hasattr(response, 'choices') else 'None'}")
                    break

                ai_response = response.choices[0].message.content.strip()
                response_time = time.time() - turn_start_time
                logger.success(
                    f"第{current_turn}轮会话完成 [response_time={response_time:.2f}s] [length={len(ai_response)}]"
                )
                if hasattr(response.choices[0], "finish_reason"):
                    logger.debug(f"响应结束: {response.choices[0].finish_reason}")

                messages.append({"role": "assistant", "content": ai_response})

                logger.debug(f"处理工具调用 [turn={current_turn}]")

                process_result = await self.unified_ai_mcp_interface.process_ai_response(
                    ai_response=ai_response,
                    user_id=user_id,
                    user_permissions=user_permissions or [],
                )

                executed_tools = process_result.get("executed_tools", [])
                write_operations = {
                    "create_issue",
                    "add_comment",
                    "merge_pull_request",
                    "close_issue",
                    "reopen_issue",
                    "close_pull_request",
                    "reopen_pull_request",
                    "add_label",
                    "remove_label",
                    "assign_user",
                    "unassign_user",
                    "request_review",
                    "create_pull_request",
                    "update_issue",
                    "update_pull_request",
                    "delete_comment",
                    "edit_comment",
                }

                has_write_operation = any(tool_name in write_operations for tool_name in executed_tools)

                if has_write_operation:
                    # logger.info(
                    #     f"写操作 [tools={executed_tools}],禁用AI回复 [session_id={session_id}]"
                    # )
                    return ""

                if process_result.get("conversation_ended", False):
                    logger.success(
                        f"对话结束 [turn={current_turn}] [reason={process_result.get('end_reason', '未知')}] [session_id={session_id}]"
                    )
                    logger.debug(f"会话统计 [total_turns={current_turn}] [final_response_length={len(ai_response)}]")
                    cleaned_response = process_result.get("cleaned_response", ai_response)
                    return cleaned_response

                if not process_result.get("has_tool_calls", False):
                    logger.success(f"会话完成 [turn={current_turn}] [reason=无工具调用] [session_id={session_id}]")
                    logger.debug(f"会话统计 [total_turns={current_turn}] [final_response_length={len(ai_response)}]")

                    cleaned_response = process_result.get("cleaned_response", ai_response)
                    should_send_response = process_result.get("should_send_response", True)

                    if not should_send_response:
                        logger.warning(f"会话结束 [reason=包含工具调用标签但无实际工具调用] [session_id={session_id}]")
                        return ""

                    return cleaned_response
                tool_results = process_result.get("tool_results", [])
                process_result.get("successful_tools", 0)
                process_result.get("failed_tools", 0)
                if not tool_results:
                    logger.warning(
                        f"会话结束 [turn={current_turn}] [reason=所有工具执行失败] [session_id={session_id}]"
                    )
                    cleaned_response = process_result.get("cleaned_response", ai_response)
                    should_send_response = process_result.get("should_send_response", True)

                    if not should_send_response:
                        logger.warning(f"会话结束 [reason=工具执行失败且包含工具调用标签] [session_id={session_id}]")
                        return ""

                    return cleaned_response

                tool_results_text = process_result.get("formatted_results", "")
                tool_message_content = f"工具执行结果:\n{tool_results_text}"
                messages.append({"role": "user", "content": tool_message_content})
                logger.info(f"工具结果消息内容: {tool_message_content}")

                logger.info(f"第{current_turn}轮工具执行完成,继续会话 [session_id={session_id}]")

            total_session_time = time.time() - int(session_id.split("_")[-1])
            logger.warning(
                f"达到最大轮数限制 [max_turns={max_turns}] [session_time={total_session_time:.2f}s] [session_id={session_id}]"
            )
            logger.info(
                f"会话统计 [total_turns={current_turn}] [messages_count={len(messages)}] [available_tools={len(available_tools)}]"
            )

            if messages and messages[-1]["role"] == "assistant":
                final_response = messages[-1]["content"]
                logger.debug(f"返回最后一轮回复 [length={len(final_response)}]")
                return final_response
            else:
                fallback_msg = "对话轮数已达上限"
                # logger.debug(f"返回轮数限制提示消息 [length={len(fallback_msg)}]")
                return fallback_msg

        except Exception as e:
            session_time = time.time() - int(session_id.split("_")[-1]) if "_" in session_id else 0
            logger.error(f"模型调用失败 [error={str(e)}] [session_time={session_time:.2f}s] [session_id={session_id}]")
            logger.debug(f"错误详情: {type(e).__name__}: {str(e)}")
            return f"模型调用失败(啊这: {str(e)}"

    def _build_initial_messages(self, context: ConversationContext, prompt: str) -> List[Dict[str, str]]:
        """构建初始消息历史"""
        messages = []

        # 添加系统提示
        messages.append(
            {
                "role": "system",
                "content": "始终保持实事求是、温柔坚定的态度。不做糖衣炮弹, 但表达要温柔而有力量。对复杂问题提供清晰、结构化且易于理解的观点。避免过度奉承, 使用俏皮、呆萌、可爱的语气与颜文字增添情绪色彩。形式专业、逻辑明确、表达有前瞻性、务实优先、不说空话, 同时注意使用“颜文字”而不是 emoji。\n\n当你需要使用MCP工具时, 请在回复中明确说明要使用的工具名称和参数, 格式如下：\n[TOOL_CALL]工具名称(参数1=值1, 参数2=值2)[/TOOL_CALL]",
            }
        )

        recent_messages = context.get_recent_messages(5)
        for msg in recent_messages:
            role = "user" if msg.role == "user" else "assistant"
            messages.append({"role": role, "content": msg.content})
        messages.append({"role": "user", "content": prompt})

        return messages

    def _format_tools_for_ai(self, available_tools: List[Dict[str, Any]]) -> str:
        """为AI格式化可用工具列表, 包含严格约束和规范说明"""
        if not available_tools:
            return "\n**当前没有可用工具**, 你不能执行任何工具操作。"

        tools_text = []
        tools_text.append("**限制：你只能使用以下明确列出的工具, 绝对不能调用任何未在此列表中的工具**\n")
        tools_text.append("### 可用工具列表")

        for tool in available_tools:
            tool_name = tool.get("name", "未知工具")
            tool_desc = tool.get("description", "无描述")
            tool_params = tool.get("parameters", {})
            tool_category = tool.get("category", "未分类")
            tools_text.append(f"**{tool_name}** ({tool_category})")
            tools_text.append(f"- 描述：{tool_desc}")
            if tool_params:
                tools_text.append("- 参数要求：")
                required_params = []
                for param_name, param_info in tool_params.items():
                    param_type = param_info.get("type", "string")
                    param_desc = param_info.get("description", "无描述")
                    param_required = param_info.get("required", False)
                    param_default = f" [默认: {param_info.get('default')}]" if "default" in param_info else ""
                    required_text = "**必需**" if param_required else "可选"
                    param_text = f"  - `{param_name}` ({param_type}, {required_text}): {param_desc}{param_default}"
                    tools_text.append(param_text)

                    if param_required:
                        required_params.append(f"{param_name}=值")

        # 添加格式规范说明
        tools_text.append("### 调用格式")
        tools_text.append("**标准格式**：`[TOOL_CALL]工具名称(参数名1=参数值1, 参数名2=参数值2)[/TOOL_CALL]`\n")

        tools_text.append("**格式要求**：")
        tools_text.append("1. 严格使用方括号标记：`[TOOL_CALL]` 和 `[/TOOL_CALL]`")
        tools_text.append("2. 工具名称必须与定义完全一致")
        tools_text.append("3. 参数格式：`参数名=参数值`, 多个参数用逗号和空格分隔")
        tools_text.append("4. 字符串参数可以不加引号（系统会自动处理）")
        tools_text.append("5. 布尔参数使用 `true` 或 `false`")
        tools_text.append("6. 数字参数直接使用数字\n")
        tools_text.append("### 约束")
        tools_text.append("1. **工具限制**：只能使用上述列出的工具, 不得调用任何其他工具")
        tools_text.append("2. **格式严格**：必须严格按照 `[TOOL_CALL]工具名(参数)[/TOOL_CALL]` 格式")
        tools_text.append("3. **参数完整**：所有标记为**必需**的参数都必须提供")
        tools_text.append("4. **参数正确**：参数名和类型必须完全符合工具定义")
        tools_text.append("5. **不可编造**：不要编造或假设任何工具调用结果")
        tools_text.append("6. **基于事实**：只基于实际工具返回的数据回复")

        return "\n".join(tools_text)

    def _parse_tool_requests_from_response(self, ai_response: str) -> List[Dict[str, Any]]:
        """从AI回复中解析工具调用请求"""
        import re

        tool_requests = []
        # 匹配 [TOOL_CALL]工具名称(参数)[/TOOL_CALL] 格式
        pattern = r"\[TOOL_CALL\]([^(]+)\(([^)]*)\)\[/TOOL_CALL\]"
        matches = re.findall(pattern, ai_response)

        for tool_name, params_str in matches:
            tool_name = tool_name.strip()
            parameters = {}
            if params_str.strip():
                param_pairs = params_str.split(",")
                for pair in param_pairs:
                    if "=" in pair:
                        key, value = pair.split("=", 1)
                        parameters[key.strip()] = value.strip().strip("\"'")

            tool_requests.append({"name": tool_name, "parameters": parameters})

            logger.debug(f"工具调用: {tool_name}, 参数: {parameters}")

        return tool_requests

    async def _execute_single_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        user_id: str,
        user_permissions: List[str],
        context: Optional[ConversationContext] = None,
    ) -> Dict[str, Any]:
        """执行单个工具调用"""
        exec_start_time = time.time()
        logger.debug(f"开始执行工具 [name={tool_name}] [user={user_id}] [params_count={len(parameters)}]")

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

        is_write_operation = tool_name in write_operations
        status_message_id = None
        group_id = None
        if is_write_operation and context and context.context_type.name == "QQ_GROUP":
            try:
                # 提取群号(存贮吧(从上下文提(x
                if "group_" in context.context_id:
                    group_id = context.context_id.split("group_")[1].split("_")[0]
                action_type = self._get_action_display_name(tool_name)
                target_repo = self._extract_target_repository(parameters)
                initiator_user = user_id
                # 发送"正在执行"消息
                status_content = (
                    f"正在执行GitHub操作...\n\n执行操作: {action_type}\n目标: {target_repo}\n触发人: {initiator_user}"
                )
                status_message_id = await self._send_qq_status_message(status_content, group_id)
                logger.debug(f"已发送GitHub操作状态消息: {status_message_id}")
            except Exception as e:
                logger.warning(f"发送GitHub操作状态消息失败: {e}")

        try:
            # 检查权限
            if hasattr(self, "mcp_tools") and self.mcp_tools:
                try:
                    mcp_tools_config = self.mcp_tools.get_available_tools()
                    if tool_name in mcp_tools_config:
                        tool_config = mcp_tools_config[tool_name]
                        required_permissions = tool_config.get("permissions", [])

                        if required_permissions:
                            # SU权限用户可以访问所有工具
                            if "qq_su" not in user_permissions:
                                # 权限映射：将工具要求的权限映射到用户权限
                                # Note: GH用户的None权限已在permission_manager中映射为Read权限
                                permission_mapping = {
                                    # 基础聊天权限 - 需要Read权限或更高
                                    "ai_chat": ["qq_read", "qq_write", "qq_su"],
                                    "github_read": [
                                        "qq_read",
                                        "qq_write",
                                        "qq_su",
                                        "github_write",
                                    ],
                                    # GH写入权限 - 需要Write权限或更高
                                    "github_write": [
                                        "qq_write",
                                        "qq_su",
                                        "github_write",
                                    ],
                                    "user_manage": ["qq_su"],
                                    "system_admin": ["qq_su"],
                                }
                                has_permission = False
                                for req_perm in required_permissions:
                                    allowed_user_perms = permission_mapping.get(req_perm, [req_perm])
                                    if any(user_perm in user_permissions for user_perm in allowed_user_perms):
                                        has_permission = True
                                        break

                                if not has_permission:
                                    logger.warning(
                                        f"用户权限不足 [tool={tool_name}] [required={required_permissions}] [user_perms={user_permissions}] [user={user_id}]"
                                    )
                                    return {
                                        "tool_name": tool_name,
                                        "success": False,
                                        "error": f"权限不足, 需要权限: {required_permissions}",
                                        "result": None,
                                    }
                            # logger.debug(
                            #     f"MCP工具权限检查通过 [tool={tool_name}] [user_perms={user_permissions}]"
                            # )
                except Exception as e:
                    logger.warning(f"MCP工具权限检查失败: {e}")

            is_valid, error_msg = SecurityValidator.validate_tool_call(tool_name, parameters)
            if not is_valid:
                logger.warning(f"工具调用验证失败 [tool={tool_name}] [error={error_msg}] [user={user_id}]")
                return {
                    "tool_name": tool_name,
                    "success": False,
                    "error": f"工具调用验证失败: {error_msg}",
                    "result": None,
                }

            # logger.debug(f"工具调用参数验证通过 [tool={tool_name}]")
            # logger.debug(
            #     f"清理工具参数 [tool={tool_name}] [original_params={list(parameters.keys())}]"
            # )
            clean_params = SecurityValidator.sanitize_parameters(tool_name, parameters)
            # logger.debug(
            #     f"参数清理完成 [tool={tool_name}] [clean_params={list(clean_params.keys())}]"
            # )
            tool_call = await self._execute_tool(tool_name, clean_params, user_id)

            exec_time = time.time() - exec_start_time
            if tool_call and tool_call.status == ToolCallStatus.SUCCESS:
                result_preview = (
                    str(tool_call.result)[:100] + "..." if len(str(tool_call.result)) > 100 else str(tool_call.result)
                )
                logger.success(f"工具执行成功 [tool={tool_name}] [exec_time={exec_time:.2f}s] [user={user_id}]")
                if is_write_operation and status_message_id and group_id:
                    try:
                        await self._recall_qq_message(int(group_id), status_message_id)
                        action_type = self._get_action_display_name(tool_name)
                        target_repo = self._extract_target_repository(parameters)
                        success_content = (
                            f"GitHub操作执行成功\n\n执行操作: {action_type}\n目标: {target_repo}\n触发人: {user_id}"
                        )
                        await self._send_qq_status_message(success_content, group_id)
                        # logger.debug(f"已发送GH操作成功提示")
                    except Exception as e:
                        logger.warning(f"发送GH操作成功提示失败: {e}")

                return {
                    "tool_name": tool_name,
                    "success": True,
                    "error": None,
                    "result": tool_call.result,
                }
            else:
                error_msg = tool_call.error if tool_call else "工具执行失败"
                logger.warning(
                    f"❌ 工具执行失败 [tool={tool_name}] [error={error_msg}] [exec_time={exec_time:.2f}s] [user={user_id}]"
                )
                if is_write_operation and status_message_id and group_id:
                    try:
                        await self._recall_qq_message(int(group_id), status_message_id)
                        action_type = self._get_action_display_name(tool_name)
                        target_repo = self._extract_target_repository(parameters)
                        failure_content = f"GitHub操作执行失败\n\n原因: {error_msg}\n执行操作: {action_type}\n目标: {target_repo}\n触发人: {user_id}"
                        await self._send_qq_status_message(int(group_id), failure_content)
                        # logger.debug(f"已发送GH操作失败提示")
                    except Exception as e:
                        logger.warning(f"发送GH操作失败提示失败: {e}")

                return {
                    "tool_name": tool_name,
                    "success": False,
                    "error": error_msg,
                    "result": None,
                }

        except Exception as e:
            exec_time = time.time() - exec_start_time
            logger.error(
                f"工具执行异常 [tool={tool_name}] [error={str(e)}] [exec_time={exec_time:.2f}s] [user={user_id}]"
            )
            logger.debug(f"详情: {type(e).__name__}: {str(e)}")

            if is_write_operation and status_message_id and group_id:
                try:
                    await self._recall_qq_message(int(group_id), status_message_id)
                    action_type = self._get_action_display_name(tool_name)
                    target_repo = self._extract_target_repository(parameters)
                    exception_content = f"GitHub操作执行失败\n\n原因: 工具执行异常: {str(e)}\n执行操作: {action_type}\n目标: {target_repo}\n触发人: {user_id}"
                    await self._send_qq_status_message(int(group_id), exception_content)
                    # logger.debug(f"已发送GH操作异常提示")
                except Exception as ex:
                    logger.warning(f"发送GH操作异常提示失败: {ex}")

            return {
                "tool_name": tool_name,
                "success": False,
                "error": f"工具执行异常: {str(e)}",
                "result": None,
            }

    async def handle_github_comment(self, payload: Dict[str, Any]) -> bool:
        """处理GitHub评论事件"""
        try:
            if not self.initialized:
                await self.initialize()

            comment = payload.get("comment", {})
            issue_or_pr = payload.get("issue") or payload.get("pull_request", {})
            repository = payload.get("repository", {})
            action = payload.get("action", "")

            repo_name = repository.get("full_name", "")
            comment_body = comment.get("body", "")
            comment_author = comment.get("user", {}).get("login", "unknown")
            comment_id = comment.get("id")
            repo_config = self.config_manager.get_repository_config(repo_name)
            if not repo_config:
                logger.info(f"仓库 {repo_name} 未在配置中, 跳过处理")
                return True

            bot_username = repo_config.get("allow_review", {}).get("bot_username", "")
            if not bot_username:
                logger.info(f"仓库 {repo_name} 未配置bot用户名, 跳过处理")
                return True
            is_bot_mentioned = f"@{bot_username}" in comment_body
            if comment_author == bot_username:
                logger.debug(f"跳过bot自身的评论")
                return True
            # 处理评论修改
            if action == "edited":
                return await self._handle_comment_edited(
                    repo_name,
                    issue_or_pr.get("number"),
                    comment_id,
                    comment_body,
                    comment_author,
                    bot_username,
                    is_bot_mentioned,
                    "pull_request" in payload,
                )
            # 处理评论删除
            if action == "deleted":
                return await self._handle_comment_deleted(
                    repo_name,
                    issue_or_pr.get("number"),
                    comment_id,
                    comment_author,
                    bot_username,
                    "pull_request" in payload,
                )

            if not is_bot_mentioned:
                # logger.debug(f"评论未提及bot {bot_username}, 跳过处理")
                return True
            # 上下文类型
            if "pull_request" in payload:
                context_type = ContextType.GITHUB_PR
                context_id = self._generate_context_id(
                    context_type,
                    repository=repo_name,
                    pr_id=str(issue_or_pr.get("number", "")),
                )
            else:
                context_type = ContextType.GITHUB_ISSUE
                context_id = self._generate_context_id(
                    context_type,
                    repository=repo_name,
                    issue_id=str(issue_or_pr.get("number", "")),
                )
            conv_context = self.context_manager.get_or_create_context(
                context_id=context_id,
                context_type=context_type,
                repository=repo_name,
                issue_or_pr_id=str(issue_or_pr.get("number", "")),
            )
            # 添加评论到上下文
            comment_message = Message(
                role="user",
                content=comment_body,
                author=comment_author,
                metadata={"comment_id": comment_id, "action": action},
            )
            conv_context.add_message(comment_message)
            logger.debug(f"为 {repo_name} 的评论生成回复")
            ai_response = await self._generate_github_ai_response(
                conv_context,
                comment_body,
                comment_author,
                repo_name,
                issue_or_pr.get("number"),
                "pull_request" in payload,
            )

            if ai_response:
                success = await self._post_github_reply(
                    repo_name, issue_or_pr.get("number"), ai_response, bot_username, comment
                )

                if success:
                    ai_message = Message(role="assistant", content=ai_response, author=bot_username)
                    conv_context.add_message(ai_message)
                    logger.success(f"回复已发布到 {repo_name}#{issue_or_pr.get('number')}")
                else:
                    logger.error(f"回复发布失败: {repo_name}#{issue_or_pr.get('number')}")
            self.context_manager.save_context(conv_context)  # 保存上下文

            return True

        except Exception as e:
            logger.error(f"处理GitHub评论异常: {e}")
            return False

    async def handle_issue_comment(self, payload: Dict[str, Any]) -> bool:
        """处理Issue评论事件"""
        return await self.handle_github_comment(payload)

    async def handle_pr_review_comment(self, payload: Dict[str, Any]) -> bool:
        """处理PR审查评论事件"""
        return await self.handle_github_comment(payload)

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self.stats,
            "contexts_count": (len(self.context_manager.contexts) if self.context_manager else 0),
            "rate_limited_users": len(self.rate_limiter.user_limits),
            "uptime": datetime.now().isoformat(),
        }

    async def _generate_github_ai_response(
        self,
        conv_context: ConversationContext,
        comment_body: str,
        comment_author: str,
        repo_name: str,
        issue_pr_number: int,
        is_pr: bool,
    ) -> str:
        """生成GitHub AI回复"""
        try:
            # 构建AI提示
            context_type = "Pull Request" if is_pr else "Issue"
            prompt = f"""你是一个GitHub助手机器人, 正在回复{context_type} #{issue_pr_number}中@{comment_author}的评论。

仓库: {repo_name}
评论内容: {comment_body}

请根据上下文提供有帮助的回复。回复应该：
1. 专业且友好
2. 针对具体问题给出建议
3. 如果需要更多信息, 礼貌地询问
4. 保持简洁明了

请直接回复, 不要包含任何前缀或后缀。"""

            if self.mcp_tools and self._is_mcp_tools_initialized():
                # 创建临时上下文
                temp_context = ConversationContext(
                    context_id=conv_context.context_id,
                    context_type=conv_context.context_type,
                    repository=repo_name,
                    issue_or_pr_id=str(issue_pr_number),
                )
                temp_context.add_message(Message(role="user", content=comment_body, author=comment_author))
                response = await self._generate_ai_response(
                    context=temp_context,
                    current_message=comment_body,
                    user_id=comment_author,
                    github_username=comment_author,
                    user_permissions=[],
                )

                if response and response.strip():
                    # 获取工具执行信息
                    tool_executions = []
                    if hasattr(temp_context, "tool_calls") and temp_context.tool_calls:
                        for tool_call in temp_context.tool_calls:
                            tool_executions.append(
                                {
                                    "tool": tool_call.name,
                                    "success": tool_call.status == ToolCallStatus.SUCCESS,
                                    "error": (tool_call.error if tool_call.error else None),
                                    "execution_time": getattr(tool_call, "execution_time", 0),
                                }
                            )
                    # 添加末尾签名
                    signature = self._generate_github_signature(tool_executions=tool_executions)
                    return f"{response.strip()}\n\n{signature}"
            signature = self._generate_github_signature()
            return f"MCP使用失败,去似吧.\n\n{signature}"

        except Exception as e:
            logger.error(f"生成AI回复异常: {e}")
            return None

    def _generate_github_signature(
        self,
        mcp_services_used: list = None,
        mcp_errors: list = None,
        tool_executions: list = None,
    ) -> str:
        """GH回复统一签名"""
        signature = "---\n✨ Powered by **baiyao105**' GitHub Bot\n\n<details><summary>🔧 执行详情</summary>\n<p>\n\n"
        if tool_executions:
            successful_tools = [exec for exec in tool_executions if exec.get("success", False)]
            failed_tools = [exec for exec in tool_executions if not exec.get("success", False)]

            total_count = len(tool_executions)
            success_count = len(successful_tools)

            signature += f"**执行统计**: {success_count}/{total_count} 个工具成功\n\n"

            if successful_tools:
                signature += "**成功执行的工具**:\n"
                for exec in successful_tools:
                    tool_name = exec.get("tool", "unknown")
                    execution_time = exec.get("execution_time", 0)
                    if execution_time > 0:
                        signature += f"  - {tool_name} ({execution_time:.2f}s)\n"
                    else:
                        signature += f"  - {tool_name}\n"
                signature += "\n"

            if failed_tools:
                signature += "**执行失败的工具**:\n"
                for exec in failed_tools:
                    tool_name = exec.get("tool", "unknown")
                    error = exec.get("error", "未知错误")
                    signature += f"  - {tool_name}: {error}\n"
                signature += "\n"
        elif mcp_services_used:
            read_services = [s for s in mcp_services_used if s.get("permission") == "read"]
            write_services = [s for s in mcp_services_used if s.get("permission") == "write"]
            if read_services:
                signature += f"**Read权限**: {', '.join([s['name'] for s in read_services])}\n"
            if write_services:
                signature += f"**Write权限**: {', '.join([s['name'] for s in write_services])}\n"
        else:
            signature += "**使用服务**: GitHub API\n"
        if mcp_errors:
            signature += f"**执行时出现错误**: {', '.join(mcp_errors)}\n"

        signature += "\n</p>\n</details>"
        return signature

    async def _handle_comment_edited(
        self,
        repo_name: str,
        issue_pr_number: int,
        comment_id: int,
        comment_body: str,
        comment_author: str,
        bot_username: str,
        is_bot_mentioned: bool,
        is_pr: bool,
    ) -> bool:
        """处理评论修改事件"""
        try:
            repo_parts = repo_name.split("/")
            if len(repo_parts) != 2:
                logger.error(f"无效的仓库名称格式: {repo_name}")
                return False
            owner, repo = repo_parts
            existing_bot_comments = await self._find_bot_replies_for_comment(
                owner, repo, issue_pr_number, comment_id, bot_username
            )

            if is_bot_mentioned:
                logger.info(f"评论修改后包含@{bot_username}, 生成新的AI回复")
                context_type = ContextType.GITHUB_PR if is_pr else ContextType.GITHUB_ISSUE
                context_id = self._generate_context_id(
                    context_type,
                    repository=repo_name,
                    pr_id=str(issue_pr_number) if is_pr else None,
                    issue_id=str(issue_pr_number) if not is_pr else None,
                )

                conv_context = self.context_manager.get_or_create_context(
                    context_id=context_id,
                    context_type=context_type,
                    repository=repo_name,
                    issue_or_pr_id=str(issue_pr_number),
                )

                ai_response = await self._generate_github_ai_response(
                    conv_context,
                    comment_body,
                    comment_author,
                    repo_name,
                    issue_pr_number,
                    is_pr,
                )

                if ai_response:
                    if existing_bot_comments:
                        # 更新现有的AI回复
                        for bot_comment in existing_bot_comments:
                            success = await self._update_github_comment(owner, repo, bot_comment["id"], ai_response)
                            if success:
                                logger.success(f"已更新回复: {repo_name}#{issue_pr_number}")
                            else:
                                logger.error(f"更新回复失败: {repo_name}#{issue_pr_number}")
                    else:
                        success = await self._post_github_reply(repo_name, issue_pr_number, ai_response, bot_username)
                        if success:
                            logger.success(f"已创建新的回复: {repo_name}#{issue_pr_number}")
                        else:
                            logger.error(f"创建回复失败: {repo_name}#{issue_pr_number}")

            else:
                # 修改后不包含@bot_name, 删除之前的回复
                if existing_bot_comments:
                    logger.info(f"评论修改后不再包含@{bot_username}, 删除之前的回复")
                    for bot_comment in existing_bot_comments:
                        success = await self._delete_github_comment(owner, repo, bot_comment["id"])
                        if success:
                            logger.success(f"已删除回复: {repo_name}#{issue_pr_number}")
                        else:
                            logger.error(f"删除回复失败: {repo_name}#{issue_pr_number}")

            return True

        except Exception as e:
            logger.error(f"处理评论修改事件异常: {e}")
            return False

    async def _find_bot_replies_for_comment(
        self,
        owner: str,
        repo: str,
        issue_pr_number: int,
        original_comment_id: int,
        bot_username: str,
    ) -> List[Dict[str, Any]]:
        """查找针对特定评论的bot回复"""
        try:
            if not self.mcp_tools or not self._is_mcp_tools_initialized():
                return []

            all_comments = await self.mcp_tools.call_tool(
                "list_comments",
                {
                    "owner": owner,
                    "repo": repo,
                    "issue_number": issue_pr_number,
                    "sort": "created",
                    "direction": "asc",
                    "limit": 600
                }
            )
            # 提取实际的评论数据
            if all_comments.get("success") and all_comments.get("data"):
                all_comments = all_comments["data"]
            else:
                all_comments = []

            bot_replies = []
            for comment in all_comments:
                # 检查是否是bot的评论
                if comment.get("author", {}).get("login") == bot_username:
                    # 检查评论内容是否包含对原评论的引用或回复标识
                    comment_body = comment.get("body", "")
                    if "✨ Powered by **baiyao105**" in comment_body or f"@{bot_username}" in comment_body:
                        bot_replies.append(comment)

            return bot_replies

        except Exception as e:
            logger.error(f"查找bot回复异常: {e}")
            return []

    async def _update_github_comment(self, owner: str, repo: str, comment_id: int, new_content: str) -> bool:
        """更新GitHub评论"""
        try:
            if not self.mcp_tools or not self._is_mcp_tools_initialized():
                return False

            result = await self.mcp_tools.update_issue_comment(
                owner=owner, repo=repo, comment_id=comment_id, body=new_content
            )

            return bool(result)

        except Exception as e:
            logger.error(f"更新GitHub评论异常: {e}")
            return False

    async def _handle_comment_deleted(
        self,
        repo_name: str,
        issue_pr_number: int,
        deleted_comment_id: int,
        comment_author: str,
        bot_username: str,
        is_pr: bool,
    ) -> bool:
        """处理评论删除事件"""
        try:
            repo_parts = repo_name.split("/")
            if len(repo_parts) != 2:
                logger.error(f"无效的仓库名称格式: {repo_name}")
                return False

            owner, repo = repo_parts
            existing_bot_comments = await self._find_bot_replies_for_comment(
                owner, repo, issue_pr_number, deleted_comment_id, bot_username
            )

            if existing_bot_comments:
                logger.info(f"评论被删除, 同步删除 {len(existing_bot_comments)} 个AI回复")

                for bot_comment in existing_bot_comments:
                    success = await self._delete_github_comment(owner, repo, bot_comment["id"])
                    if success:
                        logger.success(f"已删除回复: {repo_name}#{issue_pr_number} - 评论ID: {bot_comment['id']}")
                    else:
                        logger.error(f"删除回复失败: {repo_name}#{issue_pr_number} - 评论ID: {bot_comment['id']}")

                await self._remove_messages_from_context(repo_name, issue_pr_number, deleted_comment_id, is_pr)
            # else:
            #     logger.debug(f"被删除的评论没有对应的回复, 无需处理")

            return True

        except Exception as e:
            logger.error(f"处理评论删除事件异常: {e}")
            return False

    async def _remove_messages_from_context(
        self, repo_name: str, issue_pr_number: int, deleted_comment_id: int, is_pr: bool
    ) -> bool:
        """从上下文中移除相关消息"""
        try:
            context_type = ContextType.GITHUB_PR if is_pr else ContextType.GITHUB_ISSUE
            context_id = self._generate_context_id(
                context_type,
                repository=repo_name,
                pr_id=str(issue_pr_number) if is_pr else None,
                issue_id=str(issue_pr_number) if not is_pr else None,
            )
            conv_context = self.context_manager.get_context(context_id)
            if not conv_context:
                logger.debug(f"未找到上下文: {context_id}")
                return True

            messages_to_remove = []
            for i, message in enumerate(conv_context.messages):
                if message.metadata and message.metadata.get("comment_id") == deleted_comment_id:
                    messages_to_remove.append(i)
            # 从后往前删除, 避免索引变化
            for i in reversed(messages_to_remove):
                conv_context.messages.pop(i)
                logger.debug(f"从上下文中移除消息: 索引 {i}")
            if messages_to_remove:
                self.context_manager.save_context(conv_context)
                logger.info(f"已从上下文中移除 {len(messages_to_remove)} 条相关消息")
            return True

        except Exception as e:
            logger.error(f"从上下文移除消息异常: {e}")
            return False

    async def handle_qq_message_recall(
        self, recalled_message_id: int, operator_id: int, group_id: Optional[int] = None
    ) -> bool:
        """处理QQ消息撤回事件"""
        try:
            from .ai_models import ContextType

            context_type = ContextType.QQ_GROUP if group_id else ContextType.QQ_PRIVATE
            context_id = self._generate_context_id(
                context_type,
                group_id=str(group_id) if group_id else None,
                user_id=str(operator_id),
            )

            conv_context = self.context_manager.get_context(context_id)
            if not conv_context:
                logger.debug(f"未找到上下文: {context_id}")
                return True  # 没有上下文也算成功
            messages_to_remove = []
            bot_replies_to_recall = []

            for i, message in enumerate(conv_context.messages):
                if message.metadata and message.metadata.get("message_id") == str(recalled_message_id):
                    messages_to_remove.append(i)
                    logger.debug(f"找到被撤回的用户消息: 索引 {i}")
                    if i + 1 < len(conv_context.messages):
                        next_message = conv_context.messages[i + 1]
                        if (
                            next_message.role == "assistant"
                            and next_message.metadata
                            and next_message.metadata.get("reply_to_message_id") == str(recalled_message_id)
                        ):
                            messages_to_remove.append(i + 1)
                            ai_message_id = next_message.metadata.get("message_id")
                            if ai_message_id:
                                bot_replies_to_recall.append(ai_message_id)
                            logger.debug(f"找到对应的AI回复: 索引 {i + 1}")
            # 从后往前删除消息, 避免索引变化
            for i in reversed(messages_to_remove):
                conv_context.messages.pop(i)
                logger.debug(f"从上下文中移除消息: 索引 {i}")
            if messages_to_remove:
                self.context_manager.save_context(conv_context)
                logger.info(f"已从上下文中移除 {len(messages_to_remove)} 条相关消息")
            if bot_replies_to_recall:
                success_count = await self._recall_qq_bot_messages(bot_replies_to_recall, group_id)
                logger.success(f"成功撤回 {success_count}/{len(bot_replies_to_recall)} 条AI回复消息")

            return True

        except Exception as e:
            logger.error(f"处理QQ消息撤回异常: {e}")
            return False

    async def _recall_qq_bot_messages(self, message_ids: List[str], group_id: Optional[int] = None) -> int:
        """撤回QQ消息"""
        success_count = 0

        try:
            try:
                from nonebot import get_bot

                bot = get_bot()
            except Exception as e:
                logger.warning(f"无法获取Bot实例: {e}")
                return 0

            for message_id in message_ids:
                try:
                    await bot.delete_msg(message_id=int(message_id))
                    success_count += 1
                    logger.debug(f"成功撤回回复消息: {message_id}")
                except Exception as e:
                    logger.warning(f"撤回回复消息失败: {message_id}, 错误: {e}")

        except Exception as e:
            logger.error(f"撤回消息异常: {e}")

        return success_count

    async def _delete_github_comment(self, owner: str, repo: str, comment_id: int) -> bool:
        """删除GitHub评论"""
        try:
            if not self.mcp_tools or not self._is_mcp_tools_initialized():
                return False

            result = await self.mcp_tools.delete_issue_comment(owner=owner, repo=repo, comment_id=comment_id)

            return bool(result)

        except Exception as e:
            logger.error(f"删除GitHub评论异常: {e}")
            return False

    async def _post_github_reply(
        self,
        repo_name: str,
        issue_pr_number: int,
        reply_content: str,
        bot_username: str,
        original_comment: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """发布回复到GitHub"""
        try:
            if not self.mcp_tools or not self._is_mcp_tools_initialized():
                logger.error("MCP工具未初始化, 无法发布GitHub回复")
                return False
            repo_parts = repo_name.split("/")
            if len(repo_parts) != 2:
                logger.error(f"无效的仓库名称格式: {repo_name}")
                return False

            formatted_reply = self._format_reply_with_quote(reply_content, original_comment)
            owner, repo = repo_parts
            result = await self.mcp_tools.create_issue_comment(
                owner=owner, repo=repo, issue_number=issue_pr_number, body=formatted_reply
            )

            if result:
                logger.info(f"成功发布回复到 {repo_name}#{issue_pr_number}")
                return True
            else:
                logger.error(f"发布回复失败")
                return False

        except Exception as e:
            logger.error(f"发布GH回复异常: {e}")
            return False

    def _get_action_display_name(self, tool_name: str) -> str:
        """获取操作的显示名称"""
        action_names = {
            "create_issue": "创建Issue",
            "add_comment": "添加评论",
            "merge_pull_request": "合并PR",
            "close_issue": "关闭Issue",
            "close_pull_request": "关闭PR",
            "assign_issue": "分配Issue",
            "add_labels": "添加标签",
            "remove_labels": "移除标签",
            "create_pull_request": "创建PR",
            "update_issue": "更新Issue",
            "update_pull_request": "更新PR",
        }
        return action_names.get(tool_name, tool_name)

    def _extract_target_repository(self, parameters: Dict[str, Any]) -> str:
        """从参数中提取目标仓库信息"""
        owner = parameters.get("owner", "")
        repo = parameters.get("repo", "")
        if owner and repo:
            return f"{owner}/{repo}"
        return "未知仓库"

    def _format_reply_with_quote(self, reply_content: str, original_comment: Optional[Dict[str, Any]] = None) -> str:
        """格式化带引用的回复内容"""
        if not original_comment:
            return reply_content
        try:
            # 获取原始评论信息
            comment_body = original_comment.get("body", "")
            comment_author = original_comment.get("user", {}).get("login", "unknown")
            lines = comment_body.strip().split("\n")
            if len(lines) > 3:
                # 过长时只引用前3行，并添加省略号
                quoted_lines = lines[:3] + ["..."]
            else:
                quoted_lines = lines
            quoted_text = "\n".join(f"> {line}" for line in quoted_lines)
            formatted_reply = f"@{comment_author}\n\n{quoted_text}\n\n{reply_content}"

            return formatted_reply

        except Exception as e:
            logger.warning(f"格式化引用回复时出错: {e}")
            return reply_content

    async def _send_qq_status_message(self, group_id: int, message: str) -> Optional[str]:
        """发送状态消息并返回消息ID"""
        try:
            from .qq_msg import send_message

            result = await send_message(group_id, message)
            if result and "message_id" in result:
                return str(result["message_id"])
        except Exception as e:
            logger.error(f"发送QQ状态消息失败: {e}")
        return None

    async def _recall_qq_message(self, group_id: int, message_id: str) -> bool:
        """撤回消息"""
        try:
            from .qq_msg import _get_bot_instance

            bot = _get_bot_instance()
            if bot:
                await bot.delete_msg(message_id=int(message_id))
                return True
        except Exception as e:
            logger.error(f"撤回QQ消息失败: {e}")
        return False

    async def review_code_changes(self, pull_request: Dict[str, Any], repository: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """使用增强的AI审查引擎进行代码审查"""
        try:
            if not hasattr(self, '_review_engine'):
                from .ai_review_engine import EnhancedAIReviewEngine
                self._review_engine = EnhancedAIReviewEngine(self)
            review_result = await self._review_engine.review_code_changes(
                pull_request, repository
            )

            return review_result.to_dict()
            
        except Exception as e:
            logger.error(f"❌ AI代码审查异常: {e}")
            repo_name = repository.get("full_name", "")
            pr_number = pull_request.get("number", 0)
            
            return {
                "success": False,
                "error": str(e),
                "repository": repo_name,
                "pr_number": pr_number,
                "summary": f"审查异常: {str(e)}",
                "overall_score": 0,
                "approved": False,
                "issues_count": {"critical": 1},
                "review_content": f"审查过程中发生异常: {str(e)}"
            }

    async def cleanup(self):
        """清理资源"""
        try:
            if self.context_manager:
                self.context_manager.cleanup_expired_contexts(24)
            self.rate_limiter.cleanup_expired_limits()
            self.initialized = False

        except Exception as e:
            logger.error(f"清理AI处理器资源异常: {e}")


# 全局实例管理
_ai_handler_instance: Optional[EnhancedAIHandler] = None


def get_unified_ai_handler(config_manager=None) -> EnhancedAIHandler:
    """获取统一AI处理器实例"""
    global _ai_handler_instance
    if _ai_handler_instance is None:
        if config_manager is None:
            config_manager = get_config_manager()
        _ai_handler_instance = EnhancedAIHandler(config_manager)
    return _ai_handler_instance


def cleanup_unified_ai_handler():
    """清理统一AI处理器实例"""
    global _ai_handler_instance
    if _ai_handler_instance:
        asyncio.create_task(_ai_handler_instance.cleanup())
        _ai_handler_instance = None
