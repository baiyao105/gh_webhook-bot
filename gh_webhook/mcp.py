"""
统一MCP服务
"""

import json
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from enum import Enum
from functools import wraps
from collections import defaultdict
import hashlib

import aiohttp
from loguru import logger
from .permission_manager import get_permission_manager, QQPermissionLevel
from .ai_models import ConversationContext, ContextType, ContextManager


class MCPError(Exception):
    """MCP基础异常类"""


class MCPPermissionError(MCPError):
    """MCP权限异常"""


class MCPResourceError(MCPError):
    """MCP资源异常"""


class MCPValidationError(MCPError):
    """MCP参数验证异常"""


class ToolCategory(Enum):
    """工具分类枚举"""

    GITHUB = "github"
    CONTEXT = "context"
    SEARCH = "search"
    UTILITY = "utility"


class MCPToolCapabilities:
    """MCP工具能力管理器"""

    def __init__(self):
        self._tools = {}
        self._categories = defaultdict(list)
        self._setup_default_tools()

    def _setup_default_tools(self):
        """设置默认工具定义"""
        # GitHub工具
        github_tools = {
            "search_code": {
                "category": ToolCategory.GITHUB,
                "description": "在GitHub仓库中搜索代码",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "query": {
                        "type": "string",
                        "required": True,
                        "description": "搜索关键字",
                    },
                    "file_extension": {
                        "type": "string",
                        "required": False,
                        "description": "文件扩展名过滤",
                    },
                    "path": {
                        "type": "string",
                        "required": False,
                        "description": "路径过滤",
                    },
                    "limit": {
                        "type": "integer",
                        "required": False,
                        "description": "结果数量限制",
                        "default": 30,
                    },
                },
                "permissions": ["github_read"],
            },
            "get_file_content": {
                "category": ToolCategory.GITHUB,
                "description": "获取GitHub文件内容",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "path": {
                        "type": "string",
                        "required": True,
                        "description": "文件路径",
                    },
                    "ref": {
                        "type": "string",
                        "required": False,
                        "description": "分支或提交SHA",
                        "default": "main",
                    },
                },
                "permissions": ["github_read"],
            },
            "list_repository_files": {
                "category": ToolCategory.GITHUB,
                "description": "列出仓库文件和目录",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "path": {
                        "type": "string",
                        "required": False,
                        "description": "目录路径",
                        "default": "",
                    },
                    "ref": {
                        "type": "string",
                        "required": False,
                        "description": "分支或提交SHA",
                        "default": "main",
                    },
                },
                "permissions": ["github_read"],
            },
            "list_pull_requests": {
                "category": ToolCategory.GITHUB,
                "description": "列出仓库的Pull Requests",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "state": {
                        "type": "string",
                        "required": False,
                        "description": "PR状态(open/closed/all)",
                        "default": "open",
                    },
                    "sort": {
                        "type": "string",
                        "required": False,
                        "description": "排序方式(created/updated/popularity)",
                        "default": "created",
                    },
                    "direction": {
                        "type": "string",
                        "required": False,
                        "description": "排序方向(asc/desc)",
                        "default": "desc",
                    },
                    "limit": {
                        "type": "integer",
                        "required": False,
                        "description": "结果数量限制",
                        "default": 30,
                    },
                },
                "permissions": ["github_read"],
            },
            "get_pull_request": {
                "category": ToolCategory.GITHUB,
                "description": "获取指定PR的详细信息",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "pr_number": {
                        "type": "integer",
                        "required": True,
                        "description": "PR编号",
                    },
                },
                "permissions": ["github_read"],
            },
            "create_pull_request": {
                "category": ToolCategory.GITHUB,
                "description": "创建新的Pull Request",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "title": {
                        "type": "string",
                        "required": True,
                        "description": "PR标题",
                    },
                    "body": {
                        "type": "string",
                        "required": True,
                        "description": "PR描述",
                    },
                    "head": {
                        "type": "string",
                        "required": True,
                        "description": "源分支",
                    },
                    "base": {
                        "type": "string",
                        "required": False,
                        "description": "目标分支",
                        "default": "main",
                    },
                    "draft": {
                        "type": "boolean",
                        "required": False,
                        "description": "是否为草稿PR",
                        "default": False,
                    },
                },
                "permissions": ["github_write"],
            },
            "update_pull_request": {
                "category": ToolCategory.GITHUB,
                "description": "更新Pull Request",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "pr_number": {
                        "type": "integer",
                        "required": True,
                        "description": "PR编号",
                    },
                    "title": {
                        "type": "string",
                        "required": False,
                        "description": "新标题",
                    },
                    "body": {
                        "type": "string",
                        "required": False,
                        "description": "新描述",
                    },
                    "state": {
                        "type": "string",
                        "required": False,
                        "description": "新状态(open/closed)",
                    },
                    "base": {
                        "type": "string",
                        "required": False,
                        "description": "新目标分支",
                    },
                },
                "permissions": ["github_write"],
            },
            "merge_pull_request": {
                "category": ToolCategory.GITHUB,
                "description": "合并Pull Request",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "pr_number": {
                        "type": "integer",
                        "required": True,
                        "description": "PR编号",
                    },
                    "commit_title": {
                        "type": "string",
                        "required": False,
                        "description": "合并提交标题",
                    },
                    "commit_message": {
                        "type": "string",
                        "required": False,
                        "description": "合并提交消息",
                    },
                    "merge_method": {
                        "type": "string",
                        "required": False,
                        "description": "合并方式(merge/squash/rebase)",
                        "default": "merge",
                    },
                },
                "permissions": ["github_write"],
            },
            "list_issues": {
                "category": ToolCategory.GITHUB,
                "description": "列出仓库的Issues",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "state": {
                        "type": "string",
                        "required": False,
                        "description": "Issue状态(open/closed/all)",
                        "default": "open",
                    },
                    "sort": {
                        "type": "string",
                        "required": False,
                        "description": "排序方式(created/updated/comments)",
                        "default": "created",
                    },
                    "direction": {
                        "type": "string",
                        "required": False,
                        "description": "排序方向(asc/desc)",
                        "default": "desc",
                    },
                    "labels": {
                        "type": "string",
                        "required": False,
                        "description": "标签过滤(逗号分隔)",
                    },
                    "assignee": {
                        "type": "string",
                        "required": False,
                        "description": "分配人过滤",
                    },
                    "limit": {
                        "type": "integer",
                        "required": False,
                        "description": "结果数量限制",
                        "default": 30,
                    },
                },
                "permissions": ["github_read"],
            },
            "get_issue": {
                "category": ToolCategory.GITHUB,
                "description": "获取指定Issue的详细信息",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "issue_number": {
                        "type": "integer",
                        "required": True,
                        "description": "Issue编号",
                    },
                },
                "permissions": ["github_read"],
            },
            "create_issue": {
                "category": ToolCategory.GITHUB,
                "description": "创建新的Issue",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "title": {
                        "type": "string",
                        "required": True,
                        "description": "Issue标题",
                    },
                    "body": {
                        "type": "string",
                        "required": False,
                        "description": "Issue描述",
                    },
                    "labels": {
                        "type": "array",
                        "required": False,
                        "description": "标签列表",
                    },
                    "assignees": {
                        "type": "array",
                        "required": False,
                        "description": "分配人列表",
                    },
                    "milestone": {
                        "type": "integer",
                        "required": False,
                        "description": "里程碑编号",
                    },
                },
                "permissions": ["github_write"],
            },
            "update_issue": {
                "category": ToolCategory.GITHUB,
                "description": "更新Issue",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "issue_number": {
                        "type": "integer",
                        "required": True,
                        "description": "Issue编号",
                    },
                    "title": {
                        "type": "string",
                        "required": False,
                        "description": "新标题",
                    },
                    "body": {
                        "type": "string",
                        "required": False,
                        "description": "新描述",
                    },
                    "state": {
                        "type": "string",
                        "required": False,
                        "description": "新状态(open/closed)",
                    },
                    "labels": {
                        "type": "array",
                        "required": False,
                        "description": "新标签列表",
                    },
                    "assignees": {
                        "type": "array",
                        "required": False,
                        "description": "新分配人列表",
                    },
                    "milestone": {
                        "type": "integer",
                        "required": False,
                        "description": "新里程碑编号",
                    },
                },
                "permissions": ["github_write"],
            },
            "close_issue": {
                "category": ToolCategory.GITHUB,
                "description": "关闭Issue",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "issue_number": {
                        "type": "integer",
                        "required": True,
                        "description": "Issue编号",
                    },
                    "state_reason": {
                        "type": "string",
                        "required": False,
                        "description": "关闭原因(completed/not_planned)",
                    },
                },
                "permissions": ["github_write"],
            },
            "list_comments": {
                "category": ToolCategory.GITHUB,
                "description": "列出Issue或PR的评论",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "issue_number": {
                        "type": "integer",
                        "required": True,
                        "description": "Issue或PR编号",
                    },
                    "sort": {
                        "type": "string",
                        "required": False,
                        "description": "排序方式(created/updated)",
                        "default": "created",
                    },
                    "direction": {
                        "type": "string",
                        "required": False,
                        "description": "排序方向(asc/desc)",
                        "default": "asc",
                    },
                    "limit": {
                        "type": "integer",
                        "required": False,
                        "description": "结果数量限制",
                        "default": 30,
                    },
                },
                "permissions": ["github_read"],
            },
            "add_comment": {
                "category": ToolCategory.GITHUB,
                "description": "为Issue或PR添加评论",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "issue_number": {
                        "type": "integer",
                        "required": True,
                        "description": "Issue或PR编号",
                    },
                    "body": {
                        "type": "string",
                        "required": True,
                        "description": "评论内容",
                    },
                },
                "permissions": ["github_write"],
            },
            "create_issue_comment": {
                "category": ToolCategory.GITHUB,
                "description": "为Issue或PR创建评论（add_comment的别名）",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "issue_number": {
                        "type": "integer",
                        "required": True,
                        "description": "Issue或PR编号",
                    },
                    "body": {
                        "type": "string",
                        "required": True,
                        "description": "评论内容",
                    },
                },
                "permissions": ["github_write"],
            },
            "update_comment": {
                "category": ToolCategory.GITHUB,
                "description": "更新评论内容",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "comment_id": {
                        "type": "integer",
                        "required": True,
                        "description": "评论ID",
                    },
                    "body": {
                        "type": "string",
                        "required": True,
                        "description": "新评论内容",
                    },
                },
                "permissions": ["github_write"],
            },
            "delete_comment": {
                "category": ToolCategory.GITHUB,
                "description": "删除评论",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "comment_id": {
                        "type": "integer",
                        "required": True,
                        "description": "评论ID",
                    },
                },
                "permissions": ["github_write"],
            },
            "list_labels": {
                "category": ToolCategory.GITHUB,
                "description": "列出仓库的所有标签",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "limit": {
                        "type": "integer",
                        "required": False,
                        "description": "结果数量限制",
                        "default": 30,
                    },
                },
                "permissions": ["github_read"],
            },
            "create_label": {
                "category": ToolCategory.GITHUB,
                "description": "创建新标签",
                "parameters": {
                    "owner": {
                        "type": "string",
                        "required": True,
                        "description": "仓库所有者",
                    },
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "仓库名称",
                    },
                    "name": {
                        "type": "string",
                        "required": True,
                        "description": "标签名称",
                    },
                    "color": {
                        "type": "string",
                        "required": True,
                        "description": "标签颜色(十六进制)",
                    },
                    "description": {
                        "type": "string",
                        "required": False,
                        "description": "标签描述",
                    },
                },
                "permissions": ["github_write"],
            },
        }
        context_tools = {
            "search_conversations": {
                "category": ToolCategory.CONTEXT,
                "description": "搜索跨上下文的对话记录",
                "parameters": {
                    "query": {
                        "type": "string",
                        "required": True,
                        "description": "搜索查询",
                    },
                    "context_types": {
                        "type": "array",
                        "required": False,
                        "description": "上下文类型过滤",
                    },
                    "repositories": {
                        "type": "array",
                        "required": False,
                        "description": "仓库过滤",
                    },
                    "users": {
                        "type": "array",
                        "required": False,
                        "description": "用户过滤",
                    },
                    "start_date": {
                        "type": "string",
                        "required": False,
                        "description": "开始日期(ISO格式)",
                    },
                    "end_date": {
                        "type": "string",
                        "required": False,
                        "description": "结束日期(ISO格式)",
                    },
                    "limit": {
                        "type": "integer",
                        "required": False,
                        "description": "结果数量限制",
                        "default": 20,
                    },
                },
                "permissions": ["ai_chat"],
            },
            "get_context_stats": {
                "category": ToolCategory.CONTEXT,
                "description": "获取上下文统计信息",
                "parameters": {},
                "permissions": ["ai_chat"],
            },
            "find_related_contexts": {
                "category": ToolCategory.CONTEXT,
                "description": "查找相关的上下文",
                "parameters": {
                    "context_id": {
                        "type": "string",
                        "required": True,
                        "description": "目标上下文ID",
                    },
                    "similarity_threshold": {
                        "type": "number",
                        "required": False,
                        "description": "相似度阈值",
                        "default": 0.3,
                    },
                },
                "permissions": ["ai_chat"],
            },
            "export_context": {
                "category": ToolCategory.CONTEXT,
                "description": "导出上下文数据",
                "parameters": {
                    "context_id": {
                        "type": "string",
                        "required": True,
                        "description": "上下文ID",
                    },
                    "format": {
                        "type": "string",
                        "required": False,
                        "description": "导出格式(json/text)",
                        "default": "json",
                    },
                },
                "permissions": ["ai_chat"],
            },
        }

        for name, config in {**github_tools, **context_tools}.items():
            self.register_tool(name, config)

    def register_tool(self, name: str, config: Dict[str, Any]):
        """注册工具"""
        self._tools[name] = config
        category = config.get("category", ToolCategory.UTILITY)
        self._categories[category].append(name)
        # logger.debug(f"注册工具: {name} ({category.value})")

    def get_tool_config(self, name: str) -> Optional[Dict[str, Any]]:
        """获取工具配置"""
        return self._tools.get(name)

    def get_available_tools(self) -> Dict[str, Dict[str, Any]]:
        """获取所有可用工具"""
        return self._tools.copy()

    def get_tools_by_category(self, category: ToolCategory) -> List[str]:
        """按分类获取工具列表"""
        return self._categories.get(category, [])

    def validate_parameters(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """验证工具参数"""
        tool_config = self.get_tool_config(tool_name)
        if not tool_config:
            raise MCPValidationError(f"未知工具: {tool_name}")

        param_config = tool_config.get("parameters", {})
        validated = {}
        missing_required = []

        for param_name, param_info in param_config.items():
            if param_info.get("required", False) and param_name not in parameters:
                missing_required.append(param_name)
        if missing_required:
            required_params = []
            optional_params = []

            for param_name, param_info in param_config.items():
                param_desc = param_info.get("description", "无描述")
                param_type = param_info.get("type", "string")
                if param_info.get("required", False):
                    required_params.append(f"{param_name}=值 # {param_type}: {param_desc}")
                else:
                    default_val = param_info.get("default", "")
                    default_str = f" (默认: {default_val})" if default_val else ""
                    optional_params.append(f"[{param_name}=值] # {param_type}: {param_desc}{default_str}")

            required_str = ", ".join([p.split(" #")[0] for p in required_params])
            optional_str = ", ".join([p.split(" #")[0] for p in optional_params]) if optional_params else ""

            format_example = f"[TOOL_CALL]{tool_name}({required_str}"
            if optional_str:
                format_example += f", {optional_str}"
            format_example += ")[/TOOL_CALL]"

            error_msg = f"工具 '{tool_name}' 缺少必需参数: {', '.join(missing_required)}\n\n"
            error_msg += f"正确的调用格式:\n{format_example}\n\n"
            error_msg += f"参数说明:\n"
            error_msg += f"必需参数:\n"
            for param in required_params:
                error_msg += f"  • {param}\n"

            if optional_params:
                error_msg += f"可选参数:\n"
                for param in optional_params:
                    error_msg += f"  • {param}\n"

            error_msg += f"\n提示: 请确保按照上述格式调用工具, 所有必需参数都必须提供。"

            raise MCPValidationError(error_msg.strip())

        # 验证和转换参数
        for param_name, param_info in param_config.items():
            if param_name in parameters:
                param_value = parameters[param_name]
                param_type = param_info.get("type", "string")

                try:
                    if param_type == "integer":
                        validated[param_name] = int(param_value)
                    elif param_type == "number":
                        validated[param_name] = float(param_value)
                    elif param_type == "boolean":
                        if isinstance(param_value, bool):
                            validated[param_name] = param_value
                        elif isinstance(param_value, str):
                            validated[param_name] = param_value.lower() in (
                                "true",
                                "1",
                                "yes",
                                "on",
                            )
                        else:
                            validated[param_name] = bool(param_value)
                    elif param_type == "array":
                        if isinstance(param_value, (list, tuple)):
                            validated[param_name] = list(param_value)
                        elif isinstance(param_value, str):
                            validated[param_name] = [item.strip() for item in param_value.split(",") if item.strip()]
                        else:
                            validated[param_name] = [param_value]
                    else:  # string
                        validated[param_name] = str(param_value)

                except (ValueError, TypeError) as e:
                    param_desc = param_info.get("description", "无描述")
                    raise MCPValidationError(
                        f"工具 '{tool_name}' 参数 '{param_name}' 类型错误:\n"
                        f"期望类型: {param_type}\n"
                        f"实际收到: {type(param_value).__name__} ({param_value})\n"
                        f"参数说明: {param_desc}\n"
                        f"错误详情: {e}"
                    )
            elif "default" in param_info:
                validated[param_name] = param_info["default"]

        logger.debug(f"工具 '{tool_name}' 参数验证通过: {validated}")
        return validated


class CacheManager:
    """统一缓存管理器"""

    def __init__(self, default_ttl: int = 300):
        self.default_ttl = default_ttl
        self._caches = {
            "permissions": {},  # 权限缓存
            "github_api": {},  # GitHub API缓存
            "search_results": {},  # 搜索结果缓存
            "context_stats": {},  # 上下文统计缓存
        }
        self._timestamps = {
            "permissions": {},
            "github_api": {},
            "search_results": {},
            "context_stats": {},
        }

    def _generate_key(self, namespace: str, *args, **kwargs) -> str:
        """生成缓存键"""
        key_data = f"{namespace}:{args}:{sorted(kwargs.items())}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def get(self, namespace: str, *args, **kwargs) -> Optional[Any]:
        """获取缓存值"""
        key = self._generate_key(namespace, *args, **kwargs)

        if key not in self._caches.get(namespace, {}):
            return None
        timestamp = self._timestamps[namespace].get(key, 0)
        if time.time() - timestamp > self.default_ttl:
            self._remove(namespace, key)
            return None

        return self._caches[namespace][key]

    def set(self, namespace: str, value: Any, *args, **kwargs):
        """设置缓存值"""
        key = self._generate_key(namespace, *args, **kwargs)

        if namespace not in self._caches:
            self._caches[namespace] = {}
            self._timestamps[namespace] = {}

        self._caches[namespace][key] = value
        self._timestamps[namespace][key] = time.time()

    def _remove(self, namespace: str, key: str):
        """移除缓存项"""
        self._caches[namespace].pop(key, None)
        self._timestamps[namespace].pop(key, None)

    def clear(self, namespace: Optional[str] = None):
        """清空缓存"""
        if namespace:
            self._caches[namespace] = {}
            self._timestamps[namespace] = {}
        else:
            for ns in self._caches:
                self._caches[ns] = {}
                self._timestamps[ns] = {}
        logger.debug(f"清空缓存: {namespace or '全部'}")


class GitHubSearcher:
    """GitHub仓库搜索器"""

    def __init__(
        self,
        token: str,
        proxy_config: Optional[Dict] = None,
        cache_manager: Optional[CacheManager] = None,
    ):
        self.token = token
        self.proxy_config = proxy_config or {}
        self.cache_manager = cache_manager
        self.base_url = "https://api.github.com"
        self.session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取HTTP会话"""
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector()
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "MCP-Tools/2.0",
            }
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers=headers,
            )
        return self.session

    async def search_code(
        self,
        owner: str,
        repo: str,
        query: str,
        file_extension: Optional[str] = None,
        path: Optional[str] = None,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """在仓库中搜索代码关键字"""
        try:
            # 检查缓存
            cache_key = f"{owner}/{repo}:{query}:{file_extension}:{path}:{limit}"
            if self.cache_manager:
                cached_result = self.cache_manager.get("github_api", cache_key)
                if cached_result is not None:
                    logger.debug(f"使用缓存结果: {cache_key}")
                    return cached_result
            search_query = f"{query} repo:{owner}/{repo}"
            if file_extension:
                search_query += f" extension:{file_extension}"
            if path:
                search_query += f" path:{path}"

            params = {
                "q": search_query,
                "per_page": min(limit, 100),
                "sort": "indexed",
                "order": "desc",
            }

            session = await self._get_session()
            url = f"{self.base_url}/search/code"

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    results = []

                    for item in data.get("items", []):
                        result = {
                            "name": item.get("name"),
                            "path": item.get("path"),
                            "sha": item.get("sha"),
                            "url": item.get("html_url"),
                            "repository": {
                                "name": item.get("repository", {}).get("name"),
                                "full_name": item.get("repository", {}).get("full_name"),
                                "url": item.get("repository", {}).get("html_url"),
                            },
                            "score": item.get("score", 0),
                        }
                        results.append(result)

                    # 缓存结果
                    if self.cache_manager:
                        self.cache_manager.set("github_api", results, cache_key)

                    logger.success(f"代码搜索成功: {len(results)} 个结果")
                    return results
                else:
                    error_msg = f"GitHub API错误: {response.status}"
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"代码搜索失败: {e}")
            raise MCPResourceError(f"代码搜索失败: {str(e)}")

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str = "main") -> Dict[str, Any]:
        """获取文件内容"""
        try:
            # 检查缓存
            cache_key = f"{owner}/{repo}:{path}:{ref}"
            if self.cache_manager:
                cached_result = self.cache_manager.get("github_api", cache_key)
                if cached_result is not None:
                    logger.debug(f"使用缓存文件: {cache_key}")
                    return cached_result

            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"
            params = {"ref": ref}

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()

                    result = {
                        "name": data.get("name"),
                        "path": data.get("path"),
                        "sha": data.get("sha"),
                        "size": data.get("size"),
                        "url": data.get("html_url"),
                        "download_url": data.get("download_url"),
                        "type": data.get("type"),
                        "content": data.get("content", ""),
                        "encoding": data.get("encoding", "base64"),
                    }

                    # 缓存结果
                    if self.cache_manager:
                        self.cache_manager.set("github_api", result, cache_key)

                    logger.success(f"获取文件成功: {path}")
                    return result
                else:
                    error_msg = f"GitHub API错误: {response.status}"
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"获取文件失败: {e}")
            raise MCPResourceError(f"获取文件失败: {str(e)}")

    async def list_repository_files(
        self, owner: str, repo: str, path: str = "", ref: str = "main"
    ) -> List[Dict[str, Any]]:
        """列出仓库文件和目录"""
        try:
            # 检查缓存
            cache_key = f"{owner}/{repo}:list:{path}:{ref}"
            if self.cache_manager:
                cached_result = self.cache_manager.get("github_api", cache_key)
                if cached_result is not None:
                    logger.debug(f"使用缓存列表: {cache_key}")
                    return cached_result

            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"
            params = {"ref": ref}

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()

                    if isinstance(data, list):
                        results = []
                        for item in data:
                            result = {
                                "name": item.get("name"),
                                "path": item.get("path"),
                                "sha": item.get("sha"),
                                "size": item.get("size"),
                                "url": item.get("html_url"),
                                "type": item.get("type"),  # file or dir
                            }
                            results.append(result)
                        if self.cache_manager:
                            self.cache_manager.set("github_api", results, cache_key)

                        logger.success(f"列出文件成功: {len(results)} 个项目")
                        return results
                    else:
                        result = {
                            "name": data.get("name"),
                            "path": data.get("path"),
                            "sha": data.get("sha"),
                            "size": data.get("size"),
                            "url": data.get("html_url"),
                            "type": data.get("type"),
                        }
                        return [result]
                else:
                    error_msg = f"GitHub API错误: {response.status}"
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"列出文件失败: {e}")
            raise MCPResourceError(f"列出文件失败: {str(e)}")

    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        sort: str = "created",
        direction: str = "desc",
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """列出仓库的Pull Requests"""
        try:
            cache_key = f"{owner}/{repo}:prs:{state}:{sort}:{direction}:{limit}"
            if self.cache_manager:
                cached_result = self.cache_manager.get("github_api", cache_key)
                if cached_result is not None:
                    logger.debug(f"使用缓存PR列表: {cache_key}")
                    return cached_result
            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/pulls"
            params = {
                "state": state,
                "sort": sort,
                "direction": direction,
                "per_page": min(limit, 100),
            }

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    results = []

                    for pr in data:
                        result = {
                            "number": pr.get("number"),
                            "title": pr.get("title"),
                            "body": pr.get("body"),
                            "state": pr.get("state"),
                            "user": {
                                "login": pr.get("user", {}).get("login"),
                                "avatar_url": pr.get("user", {}).get("avatar_url"),
                            },
                            "created_at": pr.get("created_at"),
                            "updated_at": pr.get("updated_at"),
                            "merged_at": pr.get("merged_at"),
                            "html_url": pr.get("html_url"),
                            "head": {
                                "ref": pr.get("head", {}).get("ref"),
                                "sha": pr.get("head", {}).get("sha"),
                            },
                            "base": {
                                "ref": pr.get("base", {}).get("ref"),
                                "sha": pr.get("base", {}).get("sha"),
                            },
                            "mergeable": pr.get("mergeable"),
                            "draft": pr.get("draft"),
                            "labels": [
                                {"name": label.get("name"), "color": label.get("color")}
                                for label in pr.get("labels", [])
                            ],
                        }
                        results.append(result)
                    if self.cache_manager:
                        self.cache_manager.set("github_api", results, cache_key)

                    logger.success(f"获取PR列表成功: {len(results)} 个PR")
                    return results
                else:
                    error_msg = f"GitHub API错误: {response.status}"
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"获取PR列表失败: {e}")
            raise MCPResourceError(f"获取PR列表失败: {str(e)}")

    async def get_pull_request(self, owner: str, repo: str, pr_number: int) -> Dict[str, Any]:
        """获取指定PR的详细信息"""
        try:
            cache_key = f"{owner}/{repo}:pr:{pr_number}"
            if self.cache_manager:
                cached_result = self.cache_manager.get("github_api", cache_key)
                if cached_result is not None:
                    logger.debug(f"使用缓存PR: {cache_key}")
                    return cached_result

            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}"

            async with session.get(url) as response:
                if response.status == 200:
                    pr = await response.json()

                    result = {
                        "number": pr.get("number"),
                        "title": pr.get("title"),
                        "body": pr.get("body"),
                        "state": pr.get("state"),
                        "user": {
                            "login": pr.get("user", {}).get("login"),
                            "avatar_url": pr.get("user", {}).get("avatar_url"),
                        },
                        "created_at": pr.get("created_at"),
                        "updated_at": pr.get("updated_at"),
                        "merged_at": pr.get("merged_at"),
                        "closed_at": pr.get("closed_at"),
                        "html_url": pr.get("html_url"),
                        "head": {
                            "ref": pr.get("head", {}).get("ref"),
                            "sha": pr.get("head", {}).get("sha"),
                            "repo": pr.get("head", {}).get("repo", {}).get("full_name"),
                        },
                        "base": {
                            "ref": pr.get("base", {}).get("ref"),
                            "sha": pr.get("base", {}).get("sha"),
                        },
                        "mergeable": pr.get("mergeable"),
                        "mergeable_state": pr.get("mergeable_state"),
                        "merged": pr.get("merged"),
                        "draft": pr.get("draft"),
                        "commits": pr.get("commits"),
                        "additions": pr.get("additions"),
                        "deletions": pr.get("deletions"),
                        "changed_files": pr.get("changed_files"),
                        "labels": [
                            {
                                "name": label.get("name"),
                                "color": label.get("color"),
                                "description": label.get("description"),
                            }
                            for label in pr.get("labels", [])
                        ],
                        "assignees": [
                            {
                                "login": assignee.get("login"),
                                "avatar_url": assignee.get("avatar_url"),
                            }
                            for assignee in pr.get("assignees", [])
                        ],
                        "reviewers": [
                            {
                                "login": reviewer.get("login"),
                                "avatar_url": reviewer.get("avatar_url"),
                            }
                            for reviewer in pr.get("requested_reviewers", [])
                        ],
                    }
                    if self.cache_manager:
                        self.cache_manager.set("github_api", result, cache_key)

                    logger.success(f"获取PR详情成功: #{pr_number}")
                    return result
                else:
                    error_msg = f"GitHub API错误: {response.status}"
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"获取PR详情失败: {e}")
            raise MCPResourceError(f"获取PR详情失败: {str(e)}")

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        draft: bool = False,
    ) -> Dict[str, Any]:
        """创建新的Pull Request"""
        try:
            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/pulls"

            data = {
                "title": title,
                "body": body,
                "head": head,
                "base": base,
                "draft": draft,
            }

            async with session.post(url, json=data) as response:
                if response.status == 201:
                    pr = await response.json()

                    result = {
                        "number": pr.get("number"),
                        "title": pr.get("title"),
                        "body": pr.get("body"),
                        "state": pr.get("state"),
                        "html_url": pr.get("html_url"),
                        "user": {"login": pr.get("user", {}).get("login")},
                        "head": {
                            "ref": pr.get("head", {}).get("ref"),
                            "sha": pr.get("head", {}).get("sha"),
                        },
                        "base": {"ref": pr.get("base", {}).get("ref")},
                        "draft": pr.get("draft"),
                        "created_at": pr.get("created_at"),
                    }

                    logger.success(f"创建PR成功: #{pr.get('number')}")
                    return result
                else:
                    error_data = await response.json()
                    error_msg = error_data.get("message", f"GitHub API错误: {response.status}")
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"创建PR失败: {e}")
            raise MCPResourceError(f"创建PR失败: {str(e)}")

    async def update_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        title: Optional[str] = None,
        body: Optional[str] = None,
        state: Optional[str] = None,
        base: Optional[str] = None,
    ) -> Dict[str, Any]:
        """更新Pull Request"""
        try:
            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}"

            data = {}
            if title is not None:
                data["title"] = title
            if body is not None:
                data["body"] = body
            if state is not None:
                data["state"] = state
            if base is not None:
                data["base"] = base

            async with session.patch(url, json=data) as response:
                if response.status == 200:
                    pr = await response.json()

                    result = {
                        "number": pr.get("number"),
                        "title": pr.get("title"),
                        "body": pr.get("body"),
                        "state": pr.get("state"),
                        "html_url": pr.get("html_url"),
                        "updated_at": pr.get("updated_at"),
                    }
                    if self.cache_manager:
                        cache_key = f"{owner}/{repo}:pr:{pr_number}"
                        self.cache_manager._remove("github_api", cache_key)

                    logger.success(f"更新PR成功: #{pr_number}")
                    return result
                else:
                    error_data = await response.json()
                    error_msg = error_data.get("message", f"GitHub API错误: {response.status}")
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"更新PR失败: {e}")
            raise MCPResourceError(f"更新PR失败: {str(e)}")

    async def merge_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_title: Optional[str] = None,
        commit_message: Optional[str] = None,
        merge_method: str = "merge",
    ) -> Dict[str, Any]:
        """合并Pull Request"""
        try:
            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/merge"

            data = {"merge_method": merge_method}  # merge, squash, rebase
            if commit_title:
                data["commit_title"] = commit_title
            if commit_message:
                data["commit_message"] = commit_message

            async with session.put(url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    if self.cache_manager:
                        cache_key = f"{owner}/{repo}:pr:{pr_number}"
                        self.cache_manager._remove("github_api", cache_key)
                    logger.success(f"合并PR成功: #{pr_number}")
                    return {
                        "sha": result.get("sha"),
                        "merged": result.get("merged"),
                        "message": result.get("message"),
                    }
                else:
                    error_data = await response.json()
                    error_msg = error_data.get("message", f"GitHub API错误: {response.status}")
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"合并PR失败: {e}")
            raise MCPResourceError(f"合并PR失败: {str(e)}")

    async def list_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        sort: str = "created",
        direction: str = "desc",
        labels: Optional[str] = None,
        assignee: Optional[str] = None,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """列出仓库的Issues"""
        try:
            cache_key = f"{owner}/{repo}:issues:{state}:{sort}:{direction}:{labels}:{assignee}:{limit}"
            if self.cache_manager:
                cached_result = self.cache_manager.get("github_api", cache_key)
                if cached_result is not None:
                    logger.debug(f"使用缓存Issue列表: {cache_key}")
                    return cached_result

            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/issues"
            params = {
                "state": state,
                "sort": sort,
                "direction": direction,
                "per_page": min(limit, 600),
            }
            if labels:
                params["labels"] = labels
            if assignee:
                params["assignee"] = assignee

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    results = []

                    for issue in data:
                        if issue.get("pull_request"):
                            continue

                        result = {
                            "number": issue.get("number"),
                            "title": issue.get("title"),
                            "body": issue.get("body"),
                            "state": issue.get("state"),
                            "user": {
                                "login": issue.get("user", {}).get("login"),
                                "avatar_url": issue.get("user", {}).get("avatar_url"),
                            },
                            "created_at": issue.get("created_at"),
                            "updated_at": issue.get("updated_at"),
                            "closed_at": issue.get("closed_at"),
                            "html_url": issue.get("html_url"),
                            "labels": [
                                {
                                    "name": label.get("name"),
                                    "color": label.get("color"),
                                    "description": label.get("description"),
                                }
                                for label in issue.get("labels", [])
                            ],
                            "assignees": [
                                {
                                    "login": assignee.get("login"),
                                    "avatar_url": assignee.get("avatar_url"),
                                }
                                for assignee in issue.get("assignees", [])
                            ],
                            "comments": issue.get("comments", 0),
                        }
                        results.append(result)

                    if self.cache_manager:
                        self.cache_manager.set("github_api", results, cache_key)
                    # logger.success(f"获取Issue列表成功: {len(results)} 个Issue")
                    return results
                else:
                    error_msg = f"GitHub API错误: {response.status}"
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"获取Issue列表失败: {e}")
            raise MCPResourceError(f"获取Issue列表失败: {str(e)}")

    async def get_issue(self, owner: str, repo: str, issue_number: int) -> Dict[str, Any]:
        """获取指定Issue的详细信息"""
        try:
            # 检查缓存
            cache_key = f"{owner}/{repo}:issue:{issue_number}"
            if self.cache_manager:
                cached_result = self.cache_manager.get("github_api", cache_key)
                if cached_result is not None:
                    logger.debug(f"使用缓存Issue详情: {cache_key}")
                    return cached_result

            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}"

            async with session.get(url) as response:
                if response.status == 200:
                    issue = await response.json()
                    if issue.get("pull_request"):
                        raise MCPResourceError(f"#{issue_number} 是Pull Request, 不是Issue")

                    result = {
                        "number": issue.get("number"),
                        "title": issue.get("title"),
                        "body": issue.get("body"),
                        "state": issue.get("state"),
                        "user": {
                            "login": issue.get("user", {}).get("login"),
                            "avatar_url": issue.get("user", {}).get("avatar_url"),
                        },
                        "created_at": issue.get("created_at"),
                        "updated_at": issue.get("updated_at"),
                        "closed_at": issue.get("closed_at"),
                        "html_url": issue.get("html_url"),
                        "labels": [
                            {
                                "name": label.get("name"),
                                "color": label.get("color"),
                                "description": label.get("description"),
                            }
                            for label in issue.get("labels", [])
                        ],
                        "assignees": [
                            {
                                "login": assignee.get("login"),
                                "avatar_url": assignee.get("avatar_url"),
                            }
                            for assignee in issue.get("assignees", [])
                        ],
                        "milestone": (
                            {
                                "title": issue.get("milestone", {}).get("title"),
                                "number": issue.get("milestone", {}).get("number"),
                            }
                            if issue.get("milestone")
                            else None
                        ),
                        "comments": issue.get("comments", 0),
                        "closed_by": (
                            {"login": issue.get("closed_by", {}).get("login")} if issue.get("closed_by") else None
                        ),
                    }
                    if self.cache_manager:
                        self.cache_manager.set("github_api", result, cache_key)

                    logger.success(f"获取Issue详情成功: #{issue_number}")
                    return result
                else:
                    error_msg = f"GitHub API错误: {response.status}"
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"获取Issue详情失败: {e}")
            raise MCPResourceError(f"获取Issue详情失败: {str(e)}")

    async def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: Optional[str] = None,
        labels: Optional[List[str]] = None,
        assignees: Optional[List[str]] = None,
        milestone: Optional[int] = None,
    ) -> Dict[str, Any]:
        """创建新的Issue"""
        try:
            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/issues"

            data = {"title": title}
            if body:
                data["body"] = body
            if labels:
                data["labels"] = labels
            if assignees:
                data["assignees"] = assignees
            if milestone:
                data["milestone"] = milestone

            async with session.post(url, json=data) as response:
                if response.status == 201:
                    issue = await response.json()

                    result = {
                        "number": issue.get("number"),
                        "title": issue.get("title"),
                        "body": issue.get("body"),
                        "state": issue.get("state"),
                        "html_url": issue.get("html_url"),
                        "user": {"login": issue.get("user", {}).get("login")},
                        "labels": [
                            {"name": label.get("name"), "color": label.get("color")}
                            for label in issue.get("labels", [])
                        ],
                        "assignees": [{"login": assignee.get("login")} for assignee in issue.get("assignees", [])],
                        "created_at": issue.get("created_at"),
                    }

                    logger.success(f"创建Issue成功: #{issue.get('number')}")
                    return result
                else:
                    error_data = await response.json()
                    error_msg = error_data.get("message", f"GitHub API错误: {response.status}")
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"创建Issue失败: {e}")
            raise MCPResourceError(f"创建Issue失败: {str(e)}")

    async def update_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        title: Optional[str] = None,
        body: Optional[str] = None,
        state: Optional[str] = None,
        labels: Optional[List[str]] = None,
        assignees: Optional[List[str]] = None,
        milestone: Optional[int] = None,
    ) -> Dict[str, Any]:
        """更新Issue"""
        try:
            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}"

            data = {}
            if title is not None:
                data["title"] = title
            if body is not None:
                data["body"] = body
            if state is not None:
                data["state"] = state
            if labels is not None:
                data["labels"] = labels
            if assignees is not None:
                data["assignees"] = assignees
            if milestone is not None:
                data["milestone"] = milestone

            async with session.patch(url, json=data) as response:
                if response.status == 200:
                    issue = await response.json()

                    result = {
                        "number": issue.get("number"),
                        "title": issue.get("title"),
                        "body": issue.get("body"),
                        "state": issue.get("state"),
                        "html_url": issue.get("html_url"),
                        "updated_at": issue.get("updated_at"),
                    }
                    if self.cache_manager:
                        cache_key = f"{owner}/{repo}:issue:{issue_number}"
                        self.cache_manager._remove("github_api", cache_key)

                    # logger.success(f"更新Issue成功: #{issue_number}")
                    return result
                else:
                    error_data = await response.json()
                    error_msg = error_data.get("message", f"GitHub API错误: {response.status}")
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"更新Issue失败: {e}")
            raise MCPResourceError(f"更新Issue失败: {str(e)}")

    async def close_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        state_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """关闭Issue"""
        try:
            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}"

            data = {"state": "closed"}
            if state_reason:
                data["state_reason"] = state_reason  # completed, not_planned

            async with session.patch(url, json=data) as response:
                if response.status == 200:
                    issue = await response.json()

                    result = {
                        "number": issue.get("number"),
                        "title": issue.get("title"),
                        "state": issue.get("state"),
                        "closed_at": issue.get("closed_at"),
                        "html_url": issue.get("html_url"),
                    }

                    if self.cache_manager:
                        cache_key = f"{owner}/{repo}:issue:{issue_number}"
                        self.cache_manager._remove("github_api", cache_key)

                    logger.success(f"关闭Issue成功: #{issue_number}")
                    return result
                else:
                    error_data = await response.json()
                    error_msg = error_data.get("message", f"GitHub API错误: {response.status}")
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"关闭Issue失败: {e}")
            raise MCPResourceError(f"关闭Issue失败: {str(e)}")

    async def list_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        sort: str = "created",
        direction: str = "asc",
        limit: int = 600,
    ) -> List[Dict[str, Any]]:
        """列出Issue或PR的评论"""
        try:
            cache_key = f"{owner}/{repo}:comments:{issue_number}:{sort}:{direction}:{limit}"
            if self.cache_manager:
                cached_result = self.cache_manager.get("github_api", cache_key)
                if cached_result is not None:
                    logger.debug(f"使用缓存评论列表: {cache_key}")
                    return cached_result

            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}/comments"
            params = {"sort": sort, "direction": direction, "per_page": min(limit, 600)}

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    results = []

                    for comment in data:
                        result = {
                            "id": comment.get("id"),
                            "body": comment.get("body"),
                            "user": {
                                "login": comment.get("user", {}).get("login"),
                                "avatar_url": comment.get("user", {}).get("avatar_url"),
                            },
                            "created_at": comment.get("created_at"),
                            "updated_at": comment.get("updated_at"),
                            "html_url": comment.get("html_url"),
                        }
                        results.append(result)

                    if self.cache_manager:
                        self.cache_manager.set("github_api", results, cache_key)
                    logger.success(f"获取评论列表成功: {len(results)} 条评论")
                    return results
                else:
                    error_msg = f"GitHub API错误: {response.status}"
                    # logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            # logger.error(f"获取评论列表失败: {e}")
            raise MCPResourceError(f"获取评论列表失败: {str(e)}")

    async def add_comment(self, owner: str, repo: str, issue_number: int, body: str) -> Dict[str, Any]:
        """为Issue或PR添加评论"""
        try:
            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}/comments"
            data = {"body": body}

            async with session.post(url, json=data) as response:
                if response.status == 201:
                    comment = await response.json()

                    result = {
                        "id": comment.get("id"),
                        "body": comment.get("body"),
                        "user": {
                            "login": comment.get("user", {}).get("login"),
                            "avatar_url": comment.get("user", {}).get("avatar_url"),
                        },
                        "created_at": comment.get("created_at"),
                        "html_url": comment.get("html_url"),
                    }
                    if self.cache_manager:
                        cache_pattern = f"{owner}/{repo}:comments:{issue_number}:"
                    logger.success(f"添加评论成功: #{issue_number}")
                    return result
                else:
                    error_data = await response.json()
                    error_msg = error_data.get("message", f"GitHub API错误: {response.status}")
                    # logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"添加评论失败: {e}")
            raise MCPResourceError(f"添加评论失败: {str(e)}")

    async def update_comment(self, owner: str, repo: str, comment_id: int, body: str) -> Dict[str, Any]:
        """更新评论内容"""
        try:
            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/issues/comments/{comment_id}"
            data = {"body": body}

            async with session.patch(url, json=data) as response:
                if response.status == 200:
                    comment = await response.json()
                    result = {
                        "id": comment.get("id"),
                        "body": comment.get("body"),
                        "user": {"login": comment.get("user", {}).get("login")},
                        "updated_at": comment.get("updated_at"),
                        "html_url": comment.get("html_url"),
                    }

                    if self.cache_manager:
                        cache_pattern = f"{owner}/{repo}:comments:*:{comment_id}"
                        self.cache_manager._remove("github_api", cache_pattern)
                    logger.success(f"更新评论成功: {comment_id}")
                    return result
                else:
                    error_data = await response.json()
                    error_msg = error_data.get("message", f"GitHub API错误: {response.status}")
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"更新评论失败: {e}")
            raise MCPResourceError(f"更新评论失败: {str(e)}")

    async def delete_comment(self, owner: str, repo: str, comment_id: int) -> Dict[str, Any]:
        """删除评论"""
        try:
            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/issues/comments/{comment_id}"

            async with session.delete(url) as response:
                if response.status == 204:
                    # logger.success(f"删除评论成功: {comment_id}")
                    return {
                        "id": comment_id,
                        "deleted": True,
                        "message": "评论已成功删除",
                    }
                else:
                    error_data = await response.json()
                    error_msg = error_data.get("message", f"GitHub API错误: {response.status}")
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)
        except Exception as e:
            logger.error(f"删除评论失败: {e}")
            raise MCPResourceError(f"删除评论失败: {str(e)}")

    async def list_labels(self, owner: str, repo: str, limit: int = 30) -> List[Dict[str, Any]]:
        """列出仓库的所有标签"""
        try:
            cache_key = f"{owner}/{repo}:labels:{limit}"
            if self.cache_manager:
                cached_result = self.cache_manager.get("github_api", cache_key)
                if cached_result is not None:
                    logger.debug(f"使用缓存标签列表: {cache_key}")
                    return cached_result
            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/labels"
            params = {"per_page": min(limit, 100)}
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    results = []

                    for label in data:
                        result = {
                            "id": label.get("id"),
                            "name": label.get("name"),
                            "color": label.get("color"),
                            "description": label.get("description"),
                            "default": label.get("default", False),
                            "url": label.get("url"),
                        }
                        results.append(result)

                    if self.cache_manager:
                        self.cache_manager.set("github_api", results, cache_key)

                    logger.success(f"获取标签列表成功: {len(results)} 个标签")
                    return results
                else:
                    error_msg = f"GitHub API错误: {response.status}"
                    # logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            # logger.error(f"获取标签列表失败: {e}")
            raise MCPResourceError(f"获取标签列表失败: {str(e)}")

    async def create_label(
        self,
        owner: str,
        repo: str,
        name: str,
        color: str,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建新标签"""
        try:
            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/labels"
            data = {"name": name, "color": color.lstrip("#")}  # 移除颜色前的#号
            if description:
                data["description"] = description

            async with session.post(url, json=data) as response:
                if response.status == 201:
                    label = await response.json()

                    result = {
                        "id": label.get("id"),
                        "name": label.get("name"),
                        "color": label.get("color"),
                        "description": label.get("description"),
                        "url": label.get("url"),
                    }
                    if self.cache_manager:
                        cache_pattern = f"{owner}/{repo}:labels:"
                        # 唔
                    logger.success(f"创建标签成功: {name}")
                    return result
                else:
                    error_data = await response.json()
                    error_msg = error_data.get("message", f"GitHub API错误: {response.status}")
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"创建标签失败: {e}")
            raise MCPResourceError(f"创建标签失败: {str(e)}")

    async def list_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        sort: str = "created",
        direction: str = "desc",
        labels: Optional[str] = None,
        assignee: Optional[str] = None,
        limit: int = 600,
    ) -> Dict[str, Any]:
        """列出仓库的Issues"""
        try:
            cache_key = (
                f"{owner}/{repo}/issues/{state}/{sort}/{direction}/{labels or 'none'}/{assignee or 'none'}/{limit}"
            )
            if self.cache_manager:
                cached_result = self.cache_manager.get("github_api", cache_key)
                if cached_result is not None:
                    logger.debug(f"使用缓存Issues列表: {owner}/{repo}")
                    return cached_result

            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/issues"
            params = {
                "state": state,
                "sort": sort,
                "direction": direction,
                "per_page": min(limit, 600),
            }

            if labels:
                params["labels"] = labels
            if assignee:
                params["assignee"] = assignee
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    issues = await response.json()
                    result = {"total_count": len(issues), "issues": []}
                    for issue in issues[:limit]:
                        # API中PR也会出现在issues中
                        if issue.get("pull_request"):
                            continue
                        issue_data = {
                            "number": issue.get("number"),
                            "title": issue.get("title"),
                            "body": issue.get("body", "")[:500] + ("..." if len(issue.get("body", "")) > 500 else ""),
                            "state": issue.get("state"),
                            "html_url": issue.get("html_url"),
                            "user": {
                                "login": issue.get("user", {}).get("login"),
                                "avatar_url": issue.get("user", {}).get("avatar_url"),
                            },
                            "labels": [
                                {"name": label.get("name"), "color": label.get("color")}
                                for label in issue.get("labels", [])
                            ],
                            "assignees": [{"login": assignee.get("login")} for assignee in issue.get("assignees", [])],
                            "milestone": (issue.get("milestone", {}).get("title") if issue.get("milestone") else None),
                            "comments": issue.get("comments", 0),
                            "created_at": issue.get("created_at"),
                            "updated_at": issue.get("updated_at"),
                        }
                        result["issues"].append(issue_data)

                    result["total_count"] = len(result["issues"])
                    # 缓存结果
                    if self.cache_manager:
                        self.cache_manager.set("github_api", result, cache_key)

                    logger.success(f"获取Issues列表成功: {len(result['issues'])} 个")
                    return result
                else:
                    error_msg = f"GitHub API错误: {response.status}"
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"获取Issues列表失败: {e}")
            raise MCPResourceError(f"获取Issues列表失败: {str(e)}")

    async def merge_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_title: Optional[str] = None,
        commit_message: Optional[str] = None,
        merge_method: str = "merge",
    ) -> Dict[str, Any]:
        """合并Pull Request"""
        try:
            session = await self._get_session()
            url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/merge"
            data = {"merge_method": merge_method}
            if commit_title:
                data["commit_title"] = commit_title
            if commit_message:
                data["commit_message"] = commit_message

            async with session.put(url, json=data) as response:
                if response.status == 200:
                    merge_result = await response.json()

                    result = {
                        "sha": merge_result.get("sha"),
                        "merged": merge_result.get("merged", True),
                        "message": merge_result.get("message", "Pull request successfully merged"),
                    }
                    logger.success(f"合并PR成功: #{pr_number}")
                    return result
                else:
                    error_data = await response.json()
                    error_msg = error_data.get("message", f"GitHub API错误: {response.status}")
                    logger.error(f"{error_msg}")
                    raise MCPResourceError(error_msg)

        except Exception as e:
            logger.error(f"合并PR失败: {e}")
            raise MCPResourceError(f"合并PR失败: {str(e)}")

    async def close(self):
        """关闭会话"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.debug("会话已关闭")


class MCPQueryEngine:
    """跨上下文查询"""

    def __init__(
        self,
        context_manager: ContextManager,
        cache_manager: Optional[CacheManager] = None,
    ):
        self.context_manager = context_manager
        self.cache_manager = cache_manager

    def search_conversations(
        self,
        query: str,
        context_types: Optional[List[ContextType]] = None,
        repositories: Optional[List[str]] = None,
        users: Optional[List[str]] = None,
        date_range: Optional[tuple] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """搜索跨上下文的对话记录"""
        try:
            cache_key = f"search:{query}:{context_types}:{repositories}:{users}:{date_range}:{limit}"
            if self.cache_manager:
                cached_result = self.cache_manager.get("search_results", cache_key)
                if cached_result is not None:
                    logger.debug(f"使用缓存搜索结果")
                    return cached_result

            results = []
            query_lower = query.lower()
            for context_id, context in self.context_manager.contexts.items():
                if not self._match_context_filters(context, context_types, repositories, users, date_range):
                    continue

                matches = self._search_messages_in_context(context, query_lower)
                if matches:
                    context_result = {
                        "context_id": context_id,
                        "context_type": context.context_type.value,
                        "repository": context.repository,
                        "created_at": context.created_at.isoformat(),
                        "last_activity": context.last_activity.isoformat(),
                        "matches": matches,
                        "total_messages": len(context.messages),
                        "relevance_score": self._calculate_relevance(matches, query_lower),
                    }
                    results.append(context_result)
            results.sort(key=lambda x: x["relevance_score"], reverse=True)
            results = results[:limit]
            if self.cache_manager:
                self.cache_manager.set("search_results", results, cache_key)
            # logger.success(f"[查询] 搜索完成: {len(results)} 个结果")
            return results

        except Exception as e:
            logger.error(f"[查询] 搜索失败: {e}")
            raise MCPResourceError(f"搜索失败: {str(e)}")

    def _match_context_filters(
        self,
        context: ConversationContext,
        context_types: Optional[List[ContextType]],
        repositories: Optional[List[str]],
        users: Optional[List[str]],
        date_range: Optional[tuple],
    ) -> bool:
        """检查上下文是否匹配过滤条件"""
        if context_types and context.context_type not in context_types:
            return False
        if repositories and context.repository not in repositories:
            return False
        if users:
            context_users = {msg.author for msg in context.messages if msg.author}
            if not any(user in context_users for user in users):
                return False
        if date_range:
            start_date, end_date = date_range
            if not (start_date <= context.last_activity <= end_date):
                return False

        return True

    def _search_messages_in_context(self, context: ConversationContext, query_lower: str) -> List[Dict[str, Any]]:
        """在上下文中搜索消息"""
        matches = []
        for i, message in enumerate(context.messages):
            content_lower = message.content.lower()
            if query_lower in content_lower:
                match = {
                    "message_index": i,
                    "role": message.role,
                    "author": message.author,
                    "timestamp": message.timestamp.isoformat(),
                    "content": message.content,
                    "snippet": self._create_snippet(message.content, query_lower),
                }
                matches.append(match)

        return matches

    def _calculate_relevance(self, matches: List[Dict[str, Any]], query_lower: str) -> float:
        """计算相关性"""
        if not matches:
            return 0.0

        total_score = 0.0
        query_words = set(query_lower.split())
        for match in matches:
            content_lower = match["content"].lower()
            content_words = set(content_lower.split())
            # 精确匹配
            exact_matches = sum(1 for word in query_words if word in content_lower)
            exact_score = exact_matches / len(query_words) if query_words else 0
            # 词汇匹配
            word_matches = len(query_words & content_words)
            word_score = word_matches / len(query_words) if query_words else 0
            # 模糊匹配
            fuzzy_score = (
                len([w for w in content_words if any(qw in w for qw in query_words)]) / len(query_words)
                if query_words
                else 0
            )
            match_score = exact_score * 3 + word_score * 2 + fuzzy_score
            total_score += match_score

        return total_score / len(matches)

    def _create_snippet(self, content: str, query_lower: str, max_length: int = 200) -> str:
        """创建包含查询关键词的摘要片段"""
        content_lower = content.lower()
        query_pos = content_lower.find(query_lower)
        if query_pos == -1:
            return content[:max_length] + ("..." if len(content) > max_length else "")
        # 计算摘要范围
        start = max(0, query_pos - max_length // 2)
        end = min(len(content), start + max_length)
        snippet = content[start:end]
        # 添加省略号
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."

        return snippet

    def get_context_statistics(self) -> Dict[str, Any]:
        """获取上下文统计信息"""
        try:
            # 检查缓存
            if self.cache_manager:
                cached_result = self.cache_manager.get("context_stats", "global")
                if cached_result is not None:
                    logger.debug(f"使用缓存统计数据")
                    return cached_result

            stats = {
                "total_contexts": 0,
                "context_types": {},
                "total_messages": 0,
                "active_contexts_24h": 0,
                "repositories": set(),
                "users": set(),
            }

            now = datetime.now()
            day_ago = now - timedelta(days=1)
            # 统计内存中的上下文
            for context in self.context_manager.contexts.values():
                self._update_stats_with_context(stats, context, day_ago)
            # 转换集合为列表
            stats["repositories"] = list(stats["repositories"])
            stats["users"] = list(stats["users"])
            # 缓存结果
            if self.cache_manager:
                self.cache_manager.set("context_stats", stats, "global")
            return stats

        except Exception as e:
            logger.error(f"获取统计失败: {e}")
            raise MCPResourceError(f"获取统计失败: {str(e)}")

    def _update_stats_with_context(self, stats: Dict[str, Any], context: ConversationContext, day_ago: datetime):
        """更新统计信息"""
        stats["total_contexts"] += 1
        stats["total_messages"] += len(context.messages)
        context_type = context.context_type.value
        stats["context_types"][context_type] = stats["context_types"].get(context_type, 0) + 1
        # 24小时内活跃上下文
        if context.last_activity >= day_ago:
            stats["active_contexts_24h"] += 1
        # 仓库和用户统计
        if context.repository:
            stats["repositories"].add(context.repository)
        for message in context.messages:
            if message.author:
                stats["users"].add(message.author)

    def find_related_contexts(self, context_id: str, similarity_threshold: float = 0.3) -> List[Dict[str, Any]]:
        """查找相关上下文"""
        try:
            target_context = self.context_manager.contexts.get(context_id)
            if not target_context:
                logger.warning(f"目标上下文不存在: {context_id}")
                return []

            related = []
            for cid, context in self.context_manager.contexts.items():
                if cid == context_id:
                    continue
                similarity = self._calculate_context_similarity(target_context, context)
                if similarity >= similarity_threshold:
                    related.append(
                        {
                            "context_id": cid,
                            "context_type": context.context_type.value,
                            "repository": context.repository,
                            "similarity_score": similarity,
                            "last_activity": context.last_activity.isoformat(),
                            "message_count": len(context.messages),
                        }
                    )
            related.sort(key=lambda x: x["similarity_score"], reverse=True)
            logger.success(f"找到 {len(related)} 个相关上下文")
            return related

        except Exception as e:
            logger.error(f"查找失败: {e}")
            raise MCPResourceError(f"查找相关上下文失败: {str(e)}")

    def _calculate_context_similarity(self, context1: ConversationContext, context2: ConversationContext) -> float:
        """计算上下文相似度"""
        similarity_score = 0.0
        # 仓库匹配 (权重: 0.3)
        if context1.repository and context2.repository:
            if context1.repository == context2.repository:
                similarity_score += 0.3
        # 用户匹配 (权重: 0.2)
        users1 = {msg.author for msg in context1.messages if msg.author}
        users2 = {msg.author for msg in context2.messages if msg.author}
        if users1 and users2:
            user_overlap = len(users1 & users2) / len(users1 | users2)
            similarity_score += user_overlap * 0.2
        # 类型匹配 (权重: 0.1)
        if context1.context_type == context2.context_type:
            similarity_score += 0.1
        # 内容相似度 (权重: 0.4)
        content_similarity = self._calculate_content_similarity(context1, context2)
        similarity_score += content_similarity * 0.4

        return min(similarity_score, 1.0)

    def _calculate_content_similarity(self, context1: ConversationContext, context2: ConversationContext) -> float:
        """计算内容相似度"""
        # 获取最近的消息内容
        content1 = " ".join([msg.content for msg in context1.messages[-5:]])
        content2 = " ".join([msg.content for msg in context2.messages[-5:]])

        return self._calculate_text_similarity(content1, content2)

    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """计算文本相似度"""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 or not words2:
            return 0.0
        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0


class MCPTools:
    """MCP工具集"""

    def __init__(self, config_manager, context_manager=None, qq_id: str = None):
        self.config_manager = config_manager
        self.context_manager = context_manager
        self.current_qq_id = qq_id
        self.github_token = config_manager.get_github_token()
        self.proxy_config = config_manager.get("proxy", {})
        self.capabilities = MCPToolCapabilities()
        self.cache_manager = CacheManager()
        # 服务组件
        self.github_searcher = None
        self.permission_manager = None
        self.query_engine = None
        # 初始化状态
        self._initialized = False
        self._session_pool = {}

        logger.info(f"MCP初始化 - QQ: {qq_id}")

    async def initialize(self) -> bool:
        """初始化MCP工具集"""
        try:
            if self._initialized:
                return True

            self.permission_manager = get_permission_manager()
            if self.github_token:
                self.github_searcher = GitHubSearcher(self.github_token, self.proxy_config, self.cache_manager)
            else:
                logger.warning("GitHub Token不可用")
            if self.context_manager:
                self.query_engine = MCPQueryEngine(self.context_manager, self.cache_manager)

            self._initialized = True
            return True

        except Exception as e:
            logger.error(f"MCP初始化失败: {e}")
            return False

    def get_available_tools(self) -> Dict[str, Dict[str, Any]]:
        """获取所有可用工具的能力描述"""
        return self.capabilities.get_available_tools()

    async def call_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        user_id: str = None,
        user_permissions: List[str] = None,
    ) -> Dict[str, Any]:
        """调用指定的MCP工具

        Args:
            tool_name: 工具名称
            parameters: 工具参数
            user_id: 用户ID(用于权限验证)
            user_permissions: 用户权限列表(用于权限验证)
        """
        start_time = datetime.now()
        result = {"success": False, "data": None, "error": None, "execution_time": 0}

        try:
            if not self._initialized:
                await self.initialize()
            tool_config = self.capabilities.get_tool_config(tool_name)
            if not tool_config:
                raise MCPValidationError(f"未知工具: {tool_name}")
            # 验证参数
            validated_params = self.capabilities.validate_parameters(tool_name, parameters)
            # 检查权限(传递用户信息)
            await self._check_tool_permissions(tool_name, tool_config, user_id, user_permissions)
            if tool_name in self.capabilities.get_tools_by_category(ToolCategory.GITHUB):
                result["data"] = await self._call_github_tool(tool_name, validated_params)
            elif tool_name in self.capabilities.get_tools_by_category(ToolCategory.CONTEXT):
                result["data"] = await self._call_context_tool(tool_name, validated_params)
            else:
                raise MCPValidationError(f"不支持的工具类别: {tool_name}")

            result["success"] = True
            logger.success(f"工具调用成功: {tool_name}")

        except MCPPermissionError as e:
            result["error"] = f"权限错误: {str(e)}"
            logger.warning(f"{result['error']}")
        except MCPValidationError as e:
            result["error"] = f"参数错误: {str(e)}"
            logger.warning(f"{result['error']}")
        except MCPResourceError as e:
            result["error"] = f"资源错误: {str(e)}"
            logger.error(f"{result['error']}")
        except Exception as e:
            result["error"] = f"未知错误: {str(e)}"
            logger.error(f"{result['error']}")
        finally:
            result["execution_time"] = (datetime.now() - start_time).total_seconds()

        return result

    async def _check_tool_permissions(
        self,
        tool_name: str,
        tool_config: Dict[str, Any],
        user_id: str = None,
        user_permissions: List[str] = None,
    ):
        """检查工具权限(使用新的简化权限系统)

        Args:
            tool_name: 工具名称
            tool_config: 工具配置
            user_id: 用户ID(优先使用传入的用户ID)
            user_permissions: 用户权限列表(暂未使用, 保留接口)
        """
        # 优先使用传入的用户ID, 否则使用当前QQ ID
        effective_user_id = user_id or self.current_qq_id

        if not effective_user_id or not self.permission_manager:
            logger.warning(f"工具 {tool_name} 调用时缺少用户信息或权限管理器")
            return  # 跳过权限检查

        self.permission_manager.get_qq_permission(effective_user_id)
        if self.permission_manager.has_qq_permission(effective_user_id, QQPermissionLevel.SU):
            logger.debug(f"SU用户跳过权限检查 [tool={tool_name}] [user={effective_user_id}]")
            return

        read_operations = {
            'get_pull_request', 'list_pull_requests', 'get_issue', 'list_issues',
            'get_issue_comments', 'list_comments', 'search_code', 'get_file_content',
            'list_repository_files', 'list_labels', 'get_repository_info',
            'search_conversations', 'get_context_statistics', 'find_related_contexts'
        }
        
        write_operations = {
            'create_pull_request', 'update_pull_request', 'merge_pull_request',
            'create_issue', 'update_issue', 'close_issue', 'add_comment',
            'update_comment', 'delete_comment', 'create_label', 'add_labels_to_issue',
            'remove_labels_from_issue', 'assign_issue', 'unassign_issue'
        }

        if tool_name in write_operations:
            if not self.permission_manager.check_mcp_write_permission(effective_user_id, tool_name):
                raise MCPPermissionError(f"权限不足, 需要 write 权限执行 {tool_name}")
        elif tool_name in read_operations:
            if not (self.permission_manager.has_qq_permission(effective_user_id, QQPermissionLevel.READ) or
                   self.permission_manager.check_mcp_write_permission(effective_user_id, tool_name)):
                raise MCPPermissionError(f"权限不足, 需要 read 权限执行 {tool_name}")
        else:
            if not self.permission_manager.check_mcp_write_permission(effective_user_id, tool_name):
                raise MCPPermissionError(f"权限不足, 无法执行操作: {tool_name}")

        logger.debug(f"用户 {effective_user_id} 权限允许调用工具 {tool_name}")

        required_permissions = tool_config.get("permissions", [])
        if not required_permissions:
            return  # 无需权限
        permission_mapping = {
            "ai_chat": QQPermissionLevel.READ,
            "github_read": QQPermissionLevel.READ,
            "github_write": QQPermissionLevel.WRITE,
            "user_manage": QQPermissionLevel.SU,
            "system_admin": QQPermissionLevel.SU,
        }

        for old_permission in required_permissions:
            required_level = permission_mapping.get(old_permission, QQPermissionLevel.READ)
            if not self.permission_manager.has_qq_permission(effective_user_id, required_level):
                raise MCPPermissionError(f"权限不足, 需要 {required_level.value} 权限执行 {tool_name}")

    async def _call_github_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Any:
        """调用GitHub工具"""
        if not self.github_searcher:
            raise MCPResourceError("GitHub处理未初始化")
        # if地狱
        if tool_name == "search_code":
            return await self.github_searcher.search_code(
                owner=parameters["owner"],
                repo=parameters["repo"],
                query=parameters["query"],
                file_extension=parameters.get("file_extension"),
                path=parameters.get("path"),
                limit=parameters.get("limit", 30),
            )
        elif tool_name == "get_file_content":
            return await self.github_searcher.get_file_content(
                owner=parameters["owner"],
                repo=parameters["repo"],
                path=parameters["path"],
                ref=parameters.get("ref", "main"),
            )
        elif tool_name == "list_repository_files":
            return await self.github_searcher.list_repository_files(
                owner=parameters["owner"],
                repo=parameters["repo"],
                path=parameters.get("path", ""),
                ref=parameters.get("ref", "main"),
            )
        elif tool_name == "list_pull_requests":
            return await self.github_searcher.list_pull_requests(
                owner=parameters["owner"],
                repo=parameters["repo"],
                state=parameters.get("state", "open"),
                sort=parameters.get("sort", "created"),
                direction=parameters.get("direction", "desc"),
                limit=parameters.get("limit", 30),
            )
        elif tool_name == "get_pull_request":
            return await self.github_searcher.get_pull_request(
                owner=parameters["owner"],
                repo=parameters["repo"],
                pr_number=parameters["pr_number"],
            )
        elif tool_name == "create_pull_request":
            return await self.github_searcher.create_pull_request(
                owner=parameters["owner"],
                repo=parameters["repo"],
                title=parameters["title"],
                body=parameters["body"],
                head=parameters["head"],
                base=parameters.get("base", "main"),
                draft=parameters.get("draft", False),
            )
        elif tool_name == "update_pull_request":
            return await self.github_searcher.update_pull_request(
                owner=parameters["owner"],
                repo=parameters["repo"],
                pr_number=parameters["pr_number"],
                title=parameters.get("title"),
                body=parameters.get("body"),
                state=parameters.get("state"),
                base=parameters.get("base"),
            )
        elif tool_name == "merge_pull_request":
            return await self.github_searcher.merge_pull_request(
                owner=parameters["owner"],
                repo=parameters["repo"],
                pr_number=parameters["pr_number"],
                commit_title=parameters.get("commit_title"),
                commit_message=parameters.get("commit_message"),
                merge_method=parameters.get("merge_method", "merge"),
            )
        elif tool_name == "list_issues":
            return await self.github_searcher.list_issues(
                owner=parameters["owner"],
                repo=parameters["repo"],
                state=parameters.get("state", "open"),
                sort=parameters.get("sort", "created"),
                direction=parameters.get("direction", "desc"),
                labels=parameters.get("labels"),
                assignee=parameters.get("assignee"),
                limit=parameters.get("limit", 30),
            )
        elif tool_name == "get_issue":
            return await self.github_searcher.get_issue(
                owner=parameters["owner"],
                repo=parameters["repo"],
                issue_number=parameters["issue_number"],
            )
        elif tool_name == "create_issue":
            return await self.github_searcher.create_issue(
                owner=parameters["owner"],
                repo=parameters["repo"],
                title=parameters["title"],
                body=parameters.get("body"),
                labels=parameters.get("labels"),
                assignees=parameters.get("assignees"),
                milestone=parameters.get("milestone"),
            )
        elif tool_name == "update_issue":
            return await self.github_searcher.update_issue(
                owner=parameters["owner"],
                repo=parameters["repo"],
                issue_number=parameters["issue_number"],
                title=parameters.get("title"),
                body=parameters.get("body"),
                state=parameters.get("state"),
                labels=parameters.get("labels"),
                assignees=parameters.get("assignees"),
                milestone=parameters.get("milestone"),
            )
        elif tool_name == "close_issue":
            return await self.github_searcher.close_issue(
                owner=parameters["owner"],
                repo=parameters["repo"],
                issue_number=parameters["issue_number"],
                state_reason=parameters.get("state_reason"),
            )
        elif tool_name == "list_comments":
            return await self.github_searcher.list_comments(
                owner=parameters["owner"],
                repo=parameters["repo"],
                issue_number=parameters["issue_number"],
                sort=parameters.get("sort", "created"),
                direction=parameters.get("direction", "asc"),
                limit=parameters.get("limit", 30),
            )
        elif tool_name == "add_comment":
            return await self.github_searcher.add_comment(
                owner=parameters["owner"],
                repo=parameters["repo"],
                issue_number=parameters["issue_number"],
                body=parameters["body"],
            )
        elif tool_name == "create_issue_comment":
            return await self.github_searcher.add_comment(
                owner=parameters["owner"],
                repo=parameters["repo"],
                issue_number=parameters["issue_number"],
                body=parameters["body"],
            )
        elif tool_name == "update_comment":
            return await self.github_searcher.update_comment(
                owner=parameters["owner"],
                repo=parameters["repo"],
                comment_id=parameters["comment_id"],
                body=parameters["body"],
            )
        elif tool_name == "delete_comment":
            return await self.github_searcher.delete_comment(
                owner=parameters["owner"],
                repo=parameters["repo"],
                comment_id=parameters["comment_id"],
            )
        elif tool_name == "list_labels":
            return await self.github_searcher.list_labels(
                owner=parameters["owner"],
                repo=parameters["repo"],
                limit=parameters.get("limit", 30),
            )
        elif tool_name == "create_label":
            return await self.github_searcher.create_label(
                owner=parameters["owner"],
                repo=parameters["repo"],
                name=parameters["name"],
                color=parameters["color"],
                description=parameters.get("description"),
            )
        else:
            raise MCPValidationError(f"未知GitHub工具: {tool_name}")

    async def _call_context_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Any:
        """调用上下文工具"""
        if not self.query_engine:
            raise MCPResourceError("查询引擎未初始化")

        if tool_name == "search_conversations":
            context_types = parameters.get("context_types")
            if context_types:
                context_types = [ContextType(ct) for ct in context_types]
            date_range = None
            if "start_date" in parameters and "end_date" in parameters:
                start_date = datetime.fromisoformat(parameters["start_date"])
                end_date = datetime.fromisoformat(parameters["end_date"])
                date_range = (start_date, end_date)

            return self.query_engine.search_conversations(
                query=parameters["query"],
                context_types=context_types,
                repositories=parameters.get("repositories"),
                users=parameters.get("users"),
                date_range=date_range,
                limit=parameters.get("limit", 20),
            )
        elif tool_name == "get_context_stats":
            return self.query_engine.get_context_statistics()
        elif tool_name == "find_related_contexts":
            return self.query_engine.find_related_contexts(
                context_id=parameters["context_id"],
                similarity_threshold=parameters.get("similarity_threshold", 0.3),
            )
        elif tool_name == "export_context":
            return await self._export_context(
                context_id=parameters["context_id"],
                format=parameters.get("format", "json"),
            )
        else:
            raise MCPValidationError(f"未知上下文工具: {tool_name}")

    async def _export_context(self, context_id: str, format: str = "json") -> Dict[str, Any]:
        """导出上下文数据"""
        context = self.context_manager.contexts.get(context_id)
        if not context:
            context = self.context_manager.load_context(context_id)

        if not context:
            raise MCPResourceError(f"上下文未找到: {context_id}")

        if format == "json":
            return context.to_dict()
        elif format == "text":
            return self._export_context_as_text(context)
        else:
            raise MCPValidationError(f"不支持的导出格式: {format}")

    def _export_context_as_text(self, context: ConversationContext) -> str:
        """将上下文导出为文本格式"""
        lines = []
        lines.append(f"上下文ID: {context.context_id}")
        lines.append(f"类型: {context.context_type.value}")
        lines.append(f"仓库: {context.repository or '无'}")
        lines.append(f"创建时间: {context.created_at}")
        lines.append(f"最后活跃: {context.last_activity}")
        lines.append(f"消息数量: {len(context.messages)}")
        lines.append("\n=== 对话记录 ===")

        for msg in context.messages:
            timestamp = msg.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            author = f"({msg.author})" if msg.author else ""
            lines.append(f"[{timestamp}] {msg.role}{author}: {msg.content}")

        return "\n".join(lines)

    async def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> Dict[str, Any]:
        """创建issue评论 (add_comment的别名方法)
        
        Args:
            owner: 仓库所有者
            repo: 仓库名称
            issue_number: issue编号
            body: 评论内容
            
        Returns:
            Dict[str, Any]: 评论创建结果
        """
        if not self.github_searcher:
            raise MCPResourceError("GitHub处理未初始化")
        return await self.github_searcher.add_comment(owner, repo, issue_number, body)

    async def cleanup(self):
        """清理资源"""
        try:
            if self.github_searcher:
                await self.github_searcher.close()
            if self.cache_manager:
                self.cache_manager.clear()
            for session in self._session_pool.values():
                if not session.closed:
                    await session.close()

            self._session_pool.clear()
            logger.success("资源清理完成")

        except Exception as e:
            logger.error(f"资源清理失败: {e}")


class AIMessageParser:
    """AI消息解析器"""

    def __init__(self, mcp_tools: MCPTools):
        self.mcp_tools = mcp_tools
        # XML格式: <tool_call><tool_name>xxx</tool_name><parameters>xxx</parameters></tool_call>
        self.tool_pattern = re.compile(
            r"<tool_call>\s*<tool_name>([^<]+)</tool_name>\s*<parameters>([^<]*)</parameters>\s*</tool_call>",
            re.DOTALL,
        )
        # [TOOL_CALL]格式: [TOOL_CALL]tool_name(param1=value1, param2=value2)[/TOOL_CALL]
        self.bracket_tool_pattern = re.compile(r"\[TOOL_CALL\]([^(]+)\(([^)]*)\)\[/TOOL_CALL\]", re.DOTALL)
        self.json_pattern = re.compile(r"```json\s*({[^`]+})\s*```", re.DOTALL)

    def parse_ai_response(self, ai_response: str) -> Dict[str, Any]:
        """解析回复, 提取工具调用

        Args:
            ai_response: 回复内容

        Returns:
            {
                "has_tool_calls": bool,
                "tool_calls": List[Dict],
                "response_text": str,
                "error": Optional[str]
            }
        """
        result = {
            "has_tool_calls": False,
            "tool_calls": [],
            "response_text": ai_response,
            "error": None,
        }

        try:
            bracket_calls = self._parse_bracket_tool_calls(ai_response)
            if bracket_calls:
                result["tool_calls"].extend(bracket_calls)
            xml_calls = self._parse_xml_tool_calls(ai_response)
            if xml_calls:
                result["tool_calls"].extend(xml_calls)
            json_calls = self._parse_json_tool_calls(ai_response)
            if json_calls:
                result["tool_calls"].extend(json_calls)

            result["has_tool_calls"] = len(result["tool_calls"]) > 0
            if result["has_tool_calls"]:
                logger.debug(f"发现 {len(result['tool_calls'])} 个工具调用")

        except Exception as e:
            result["error"] = f"解析回复失败: {str(e)}"
            logger.error(f"{result['error']}")

        return result

    def _parse_bracket_tool_calls(self, text: str) -> List[Dict[str, Any]]:
        """解析工具调用"""
        tool_calls = []

        incomplete_patterns = [
            r"\[TOOL_CALL\][^\[]*(?!\[/TOOL_CALL\])",  # 缺少结束标签
            r"(?<!\[TOOL_CALL\])[^\]]*\[/TOOL_CALL\]",  # 缺少开始标签
            r"\[TOOL_CALL\][^(]*\([^)]*(?!\))\[/TOOL_CALL\]",  # 括号不匹配
        ]

        for pattern in incomplete_patterns:
            if re.search(pattern, text):
                logger.warning(f"不完整的工具调用格式")
                break

        for match in self.bracket_tool_pattern.finditer(text):
            tool_name = match.group(1).strip()
            params_text = match.group(2).strip()

            if not tool_name:
                logger.error(f"工具调用格式错误: 工具名称为空")
                continue
            if not self.mcp_tools.capabilities.get_tool_config(tool_name):
                available_tools = list(self.mcp_tools.capabilities.get_available_tools().keys())
                logger.error(f"未知工具: '{tool_name}'\n")
                continue

            try:
                parameters = {}
                if params_text:
                    param_pairs = self._smart_split_parameters(params_text)
                    for pair in param_pairs:
                        if "=" not in pair:
                            logger.warning(f"参数格式错误: '{pair}' (应为 key=value 格式)")
                            continue

                        key, value = pair.split("=", 1)
                        key = key.strip()
                        value = value.strip()

                        if not key:
                            logger.warning(f"参数名为空: '{pair}'")
                            continue
                        parameters[key] = self._parse_parameter_value(value)
                try:
                    validated_params = self.mcp_tools.capabilities.validate_parameters(tool_name, parameters)

                    tool_calls.append(
                        {
                            "tool_name": tool_name,
                            "parameters": validated_params,
                            "format": "bracket",
                        }
                    )

                    logger.info(f"成功解析工具调用: {tool_name} - {validated_params}")

                except MCPValidationError as ve:
                    logger.error(f"工具参数验证失败:\n{ve}")
                    continue

            except Exception as e:
                logger.error(f"[TOOL_CALL]格式解析失败: {tool_name} - {e}")
                continue

        return tool_calls

    def _smart_split_parameters(self, params_text: str) -> List[str]:
        """分割参数"""
        params = []
        current_param = ""
        in_quotes = False
        quote_char = None
        paren_depth = 0

        for char in params_text:
            if char in ('"', "'") and not in_quotes:
                in_quotes = True
                quote_char = char
                current_param += char
            elif char == quote_char and in_quotes:
                in_quotes = False
                quote_char = None
                current_param += char
            elif char == "(" and not in_quotes:
                paren_depth += 1
                current_param += char
            elif char == ")" and not in_quotes:
                paren_depth -= 1
                current_param += char
            elif char == "," and not in_quotes and paren_depth == 0:
                if current_param.strip():
                    params.append(current_param.strip())
                current_param = ""
            else:
                current_param += char

        if current_param.strip():
            params.append(current_param.strip())

        return params

    def _parse_parameter_value(self, value: str) -> Any:
        """解析参数值的类型"""
        value = value.strip()
        # 布尔值
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        # 整数
        if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
            return int(value)
        # 浮点数
        try:
            if "." in value:
                return float(value)
        except ValueError:
            pass
        # 数组格式: [item1, item2, item3]
        if value.startswith("[") and value.endswith("]"):
            try:
                array_content = value[1:-1].strip()
                if not array_content:
                    return []
                items = [item.strip().strip('"').strip("'") for item in array_content.split(",")]
                return [item for item in items if item]
            except Exception:
                pass
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            return value[1:-1]

        return value

    def _parse_xml_tool_calls(self, text: str) -> List[Dict[str, Any]]:
        """解析XML格式的工具调用"""
        tool_calls = []

        for match in self.tool_pattern.finditer(text):
            tool_name = match.group(1).strip()
            params_text = match.group(2).strip()
            try:
                if params_text:
                    parameters = json.loads(params_text)
                else:
                    parameters = {}

                tool_calls.append({"tool_name": tool_name, "parameters": parameters, "format": "xml"})

            except json.JSONDecodeError:
                logger.warning(f"工具调用参数解析失败: {tool_name}")

        return tool_calls

    def _parse_json_tool_calls(self, text: str) -> List[Dict[str, Any]]:
        """解析JSON格式的工具调用"""
        tool_calls = []

        for match in self.json_pattern.finditer(text):
            try:
                json_data = json.loads(match.group(1))
                if isinstance(json_data, dict) and "tool_name" in json_data:
                    tool_calls.append(
                        {
                            "tool_name": json_data["tool_name"],
                            "parameters": json_data.get("parameters", {}),
                            "format": "json",
                        }
                    )
                elif isinstance(json_data, dict) and "function" in json_data:
                    func_data = json_data["function"]
                    tool_calls.append(
                        {
                            "tool_name": func_data["name"],
                            "parameters": json.loads(func_data.get("arguments", "{}")),
                            "format": "openai",
                        }
                    )

            except json.JSONDecodeError:
                continue

        return tool_calls

    def _extract_parameters_from_context(self, text: str, tool_name: str) -> Dict[str, Any]:
        """从上下文中提取工具参数"""
        params = {}

        # 提取仓库信息
        repo_patterns = [
            r"(?:仓库|repo|repository)[：:]?\s*([\w\-\.]+/[\w\-\.]+)",  # 直接格式
            r"github\.com/([\w\-\.]+/[\w\-\.]+)",  # GitHub URL格式
            r"([\w\-\.]+/[\w\-\.]+)(?:/pull|/issues|/tree)",  # URL路径格式
        ]

        for pattern in repo_patterns:
            repo_match = re.search(pattern, text, re.IGNORECASE)
            if repo_match:
                repo_full = repo_match.group(1)
                if "/" in repo_full:
                    owner, repo = repo_full.split("/", 1)
                    params["owner"] = owner
                    params["repo"] = repo
                    break

        # 没找到仓库信息时尝试从上下文管理器获取当前仓库信息
        if "owner" not in params and hasattr(self, "context_manager"):
            current_context = getattr(self.context_manager, "current_context", None)
            if current_context and hasattr(current_context, "repository"):
                repo_info = current_context.repository
                if repo_info and "/" in repo_info:
                    owner, repo = repo_info.split("/", 1)
                    params["owner"] = owner
                    params["repo"] = repo

        file_pattern = r"(?:文件|file)[：:]?\s*([\w\-\./]+\.[\w]+)"
        file_match = re.search(file_pattern, text, re.IGNORECASE)
        if file_match:
            params["path"] = file_match.group(1)
        if "搜索" in text or "search" in text.lower():
            query_pattern = r'[""](.*?)[""]'
            query_match = re.search(query_pattern, text)
            if query_match:
                params["query"] = query_match.group(1)

        return params

    async def execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
        user_id: str = None,
        user_permissions: List[str] = None,
    ) -> List[Dict[str, Any]]:
        """执行解析出的工具调用

        Args:
            tool_calls: 工具调用列表
            user_id: 用户ID(用于权限验证)
            user_permissions: 用户权限列表(用于权限验证)

        Returns:
            执行结果列表
        """
        results = []

        for tool_call in tool_calls:
            tool_name = tool_call["tool_name"]
            parameters = tool_call["parameters"]

            try:
                result = await self.mcp_tools.call_tool(tool_name, parameters, user_id, user_permissions)
                results.append(
                    {
                        "tool_name": tool_name,
                        "success": result["success"],
                        "data": result["data"],
                        "error": result["error"],
                        "execution_time": result["execution_time"],
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "tool_name": tool_name,
                        "success": False,
                        "data": None,
                        "error": f"工具执行失败: {str(e)}",
                        "execution_time": 0,
                    }
                )
                logger.error(f"工具执行失败 {tool_name}: {e}")

        return results


_mcp_tools: Optional[MCPTools] = None
_ai_parser: Optional[AIMessageParser] = None


def get_mcp_tools(config_manager, context_manager=None, qq_id: str = None) -> MCPTools:
    """获取MCP工具实例"""
    global _mcp_tools
    if _mcp_tools is None:
        _mcp_tools = MCPTools(config_manager, context_manager, qq_id)
    return _mcp_tools


def get_ai_message_parser(config_manager, context_manager=None, qq_id: str = None) -> AIMessageParser:
    """获取消息解析器实例"""
    global _ai_parser, _mcp_tools
    if _mcp_tools is None:
        _mcp_tools = MCPTools(config_manager, context_manager, qq_id)
    if _ai_parser is None:
        _ai_parser = AIMessageParser(_mcp_tools)

    return _ai_parser


async def initialize_mcp_tools(config_manager, context_manager=None, qq_id: str = None) -> bool:
    """初始化MCP工具"""
    tools = get_mcp_tools(config_manager, context_manager, qq_id)
    return await tools.initialize()


async def cleanup_mcp_tools():
    """清理MCP工具资源"""
    global _mcp_tools, _ai_parser, _unified_interface
    if _mcp_tools:
        await _mcp_tools.cleanup()
        _mcp_tools = None
    _ai_parser = None
    _unified_interface = None


class UnifiedAIMCPInterface:
    """统一的AI-MCP接口"""

    def __init__(self, mcp_tools: MCPTools, ai_parser: AIMessageParser):
        self.mcp_tools = mcp_tools
        self.ai_parser = ai_parser
        self.logger = logger

    async def process_ai_response(
        self, ai_response: str, user_id: str = None, user_permissions: List[str] = None
    ) -> Dict[str, Any]:
        """处理AI回复, 解析并执行工具调用

        Args:
            ai_response: AI的回复内容
            user_id: 用户ID(可选)
            user_permissions: 用户权限列表(可选)

        Returns:
            Dict包含:
            - has_tool_calls: 是否包含工具调用
            - tool_results: 工具执行结果列表
            - success_count: 成功执行的工具数量
            - failed_count: 失败的工具数量
            - formatted_results: 格式化的结果文本
            - conversation_ended: AI是否明确表示对话结束
        """
        try:
            conversation_ended = self._detect_conversation_end(ai_response)
            if conversation_ended:
                return {
                    "has_tool_calls": False,
                    "tool_results": [],
                    "success_count": 0,
                    "failed_count": 0,
                    "formatted_results": "",
                    "cleaned_response": ai_response,
                    "should_send_response": True,
                    "conversation_ended": True,
                }
            parse_result = self.ai_parser.parse_ai_response(ai_response)
            tool_calls = parse_result.get("tool_calls", [])

            if not tool_calls:
                return {
                    "has_tool_calls": False,
                    "tool_results": [],
                    "success_count": 0,
                    "failed_count": 0,
                    "formatted_results": "",
                    "cleaned_response": ai_response,
                    "should_send_response": True,
                    "conversation_ended": False,
                }

            self.logger.debug(f"检测到 {len(tool_calls)} 个工具调用")
            tool_results = await self.ai_parser.execute_tool_calls(tool_calls, user_id, user_permissions)
            success_count = sum(1 for result in tool_results if result.get("success", False))
            failed_count = len(tool_results) - success_count

            for result in tool_results:
                tool_name = result.get("tool_name", "unknown")
                if result.get("success", False):
                    self.logger.success(f"工具 {tool_name} 执行成功")
                else:
                    self.logger.warning(f"工具 {tool_name} 执行失败: {result.get('error', 'Unknown error')}")
            formatted_results = self._format_tool_results(tool_results)
            cleaned_response = self._clean_response_text(ai_response)

            return {
                "has_tool_calls": True,
                "tool_results": tool_results,
                "success_count": success_count,
                "failed_count": failed_count,
                "formatted_results": formatted_results,
                "cleaned_response": cleaned_response,
                "should_send_response": bool(cleaned_response.strip()),  # 只有在有非工具调用内容时才发送
                "conversation_ended": False,
            }

        except Exception as e:
            self.logger.error(f"处理AI回复时发生异常: {e}")
            return {
                "has_tool_calls": False,
                "tool_results": [],
                "success_count": 0,
                "failed_count": 0,
                "formatted_results": f"处理AI回复时发生错误: {str(e)}",
                "conversation_ended": False,
            }

    def _detect_conversation_end(self, ai_response: str) -> bool:
        """检测AI是否明确表示对话结束

        Args:
            ai_response: AI的回复内容

        Returns:
            bool: 是否检测到对话结束信号
        """
        end_patterns = [
            r"\[\s*END\s*\]",  # [END]
            r"\[\s*DONE\s*\]",  # [DONE]
            r"\[\s*COMPLETE\s*\]",  # [COMPLETE]
            r"\[\s*FINISHED\s*\]",  # [FINISHED]
            r"\[\s*对话结束\s*\]",  # [对话结束]
            r"\[\s*完成\s*\]",  # [完成]
        ]

        for pattern in end_patterns:
            if re.search(pattern, ai_response, re.IGNORECASE):
                self.logger.info(f"🔍 检测到对话结束标记: {pattern}")
                return True

        return False

    def _clean_response_text(self, text: str) -> str:
        """清理文本"""
        cleaned = re.sub(r"\[TOOL_CALL\].*?\[/TOOL_CALL\]", "", text, flags=re.DOTALL)
        cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"\n\s*\n", "\n", cleaned)
        return cleaned.strip()

    def _format_tool_results(self, tool_results: List[Dict[str, Any]]) -> str:
        """格式化工具执行结果"""
        if not tool_results:
            return ""

        formatted_parts = []
        for result in tool_results:
            tool_name = result.get("tool_name", "未知工具")
            if result.get("success", False):
                tool_result = result.get("data", "")
                if isinstance(tool_result, dict):
                    tool_result = json.dumps(tool_result, ensure_ascii=False, indent=2)
                elif tool_result is None:
                    tool_result = ""
                formatted_parts.append(f"{tool_name}: {tool_result}")
            else:
                error_msg = result.get("error", "未知错误")
                formatted_parts.append(f"{tool_name}: {error_msg}")

        return "\n".join(formatted_parts)

    async def get_available_tools(self) -> List[Dict[str, Any]]:
        """获取可用的工具列表"""
        try:
            return await self.mcp_tools.get_available_tools()
        except Exception as e:
            self.logger.error(f"获取可用工具列表失败: {e}")
            return []

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "mcp_tools_initialized": self.mcp_tools is not None,
            "ai_parser_initialized": self.ai_parser is not None,
        }


# 全局统一接口实例
_unified_interface: Optional[UnifiedAIMCPInterface] = None


def get_unified_ai_mcp_interface(
    config_manager, context_manager=None, qq_id: str = None
) -> Optional[UnifiedAIMCPInterface]:
    """获取统一的AI-MCP接口实例"""
    global _unified_interface
    if _unified_interface is None:
        mcp_tools = get_mcp_tools(config_manager, context_manager, qq_id)
        ai_parser = get_ai_message_parser(config_manager, context_manager, qq_id)
        if mcp_tools and ai_parser:
            _unified_interface = UnifiedAIMCPInterface(mcp_tools, ai_parser)
    return _unified_interface


__all__ = [
    "MCPTools",
    "AIMessageParser",
    "UnifiedAIMCPInterface",
    "MCPError",
    "MCPPermissionError",
    "MCPResourceError",
    "MCPValidationError",
    "MCPQueryEngine",
    "GitHubSearcher",
    "CacheManager",
    "ToolCategory",
    "get_mcp_tools",
    "get_ai_message_parser",
    "get_unified_ai_mcp_interface",
    "initialize_mcp_tools",
    "cleanup_mcp_tools",
]
