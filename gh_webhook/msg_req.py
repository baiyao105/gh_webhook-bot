"""
通知处理
"""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger


class MessagePlatform(Enum):
    """消息平台类型"""

    QQ = "qq"


class MessageType(Enum):
    """消息类型"""

    PUSH = "push"  # 推送事件
    PULL_REQUEST = "pull_request"  # PR事件
    ISSUES = "issues"  # Issues事件
    RELEASE = "release"  # 发布事件
    STAR = "star"  # 星标事件
    FORK = "fork"  # Fork事件
    WATCH = "watch"  # Watch事件
    CREATE = "create"  # 创建事件
    DELETE = "delete"  # 删除事件
    WORKFLOW = "workflow_run"  # 工作流事件
    SYSTEM = "system"  # 系统消息
    COMMIT_COMMENT = "commit_comment"  # 提交评论
    DISCUSSION = "discussion"  # 讨论
    GOLLUM = "gollum"  # Wiki页面
    MEMBER = "member"  # 成员管理
    MEMBERSHIP = "membership"  # 团队成员
    MILESTONE = "milestone"  # 里程碑
    PROJECT = "project"  # 项目
    PROJECT_CARD = "project_card"  # 项目卡片
    PROJECT_COLUMN = "project_column"  # 项目列
    PUBLIC = "public"  # 仓库公开
    PULL_REQUEST_REVIEW = "pull_request_review"  # PR审查
    PULL_REQUEST_REVIEW_COMMENT = "pull_request_review_comment"  # PR审查评论
    REPOSITORY = "repository"  # 仓库事件
    STATUS = "status"  # 状态检查
    TEAM = "team"  # 团队
    TEAM_ADD = "team_add"  # 团队添加
    CHECK_RUN = "check_run"  # 检查运行
    CHECK_SUITE = "check_suite"  # 检查套件
    DEPLOYMENT = "deployment"  # 部署
    DEPLOYMENT_STATUS = "deployment_status"  # 部署状态
    PAGE_BUILD = "page_build"  # 页面构建
    PING = "ping"  # Ping事件
    AI_REVIEW = "ai_review"  # 我也不知道为什么出现


@dataclass
class MessageContent:
    """消息内容"""

    title: str
    content: str
    summary: Optional[str] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    mentions: Optional[List[str]] = None  # 需要提及的GitHub用户名列表


@dataclass
class NotificationTarget:
    """通知目标"""

    platform: MessagePlatform
    target_id: str  # QQ群号
    config: Optional[Dict[str, Any]] = None


@dataclass
class MessageRequest:
    """消息请求"""

    message_type: MessageType
    content: MessageContent
    targets: List[NotificationTarget]
    priority: int = 5  # 1-10, 数字越大优先级越高
    retry_count: int = 0
    max_retries: int = 3
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


# 事件图标映射
EVENT_ICONS = {
    "push": "📤",
    "pull_request": "🔀",
    "issues": "🐛",
    "release": "🚀",
    "star": "⭐",
    "fork": "🍴",
    "watch": "👀",
    "create": "🆕",
    "delete": "🗑️",
    "workflow_run": "⚙️",
    "ai_review": "🤖",
    "system": "📋",
    "default": "📋",
    "commit_comment": "💬",
    "discussion": "💭",
    "gollum": "📖",
    "member": "👥",
    "membership": "🏢",
    "milestone": "🎯",
    "project": "📊",
    "project_card": "🃏",
    "project_column": "📋",
    "public": "🌍",
    "pull_request_review": "👁️",
    "pull_request_review_comment": "💬",
    "repository": "📁",
    "status": "📊",
    "team": "👥",
    "team_add": "➕",
    "check_run": "✅",
    "check_suite": "📋",
    "deployment": "🚀",
    "deployment_status": "📊",
    "page_build": "📄",
    "ping": "🏓",
}


class MessageFormatter:
    """消息格式化器"""

    def __init__(self, global_config: Optional[Dict[str, Any]] = None):
        self.global_config = global_config or {}
        self.formatters = {
            MessageType.PUSH: self._format_push_message,
            MessageType.PULL_REQUEST: self._format_pr_message,
            MessageType.ISSUES: self._format_issues_message,
            MessageType.RELEASE: self._format_release_message,
            MessageType.STAR: self._format_star_message,
            MessageType.FORK: self._format_fork_message,
            MessageType.WATCH: self._format_watch_message,
            MessageType.CREATE: self._format_create_message,
            MessageType.DELETE: self._format_delete_message,
            MessageType.WORKFLOW: self._format_workflow_message,
            MessageType.SYSTEM: self._format_system_message,
            MessageType.COMMIT_COMMENT: self._format_commit_comment_message,
            MessageType.DISCUSSION: self._format_discussion_message,
            MessageType.GOLLUM: self._format_gollum_message,
            MessageType.MEMBER: self._format_member_message,
            MessageType.MEMBERSHIP: self._format_membership_message,
            MessageType.MILESTONE: self._format_milestone_message,
            MessageType.PROJECT: self._format_project_message,
            MessageType.PROJECT_CARD: self._format_project_card_message,
            MessageType.PROJECT_COLUMN: self._format_project_column_message,
            MessageType.PUBLIC: self._format_public_message,
            MessageType.PULL_REQUEST_REVIEW: self._format_pr_review_message,
            MessageType.PULL_REQUEST_REVIEW_COMMENT: self._format_pr_review_comment_message,
            MessageType.REPOSITORY: self._format_repository_message,
            MessageType.STATUS: self._format_status_message,
            MessageType.TEAM: self._format_team_message,
            MessageType.TEAM_ADD: self._format_team_add_message,
            MessageType.CHECK_RUN: self._format_check_run_message,
            MessageType.CHECK_SUITE: self._format_check_suite_message,
            MessageType.DEPLOYMENT: self._format_deployment_message,
            MessageType.DEPLOYMENT_STATUS: self._format_deployment_status_message,
            MessageType.PAGE_BUILD: self._format_page_build_message,
            MessageType.PING: self._format_ping_message,
            MessageType.AI_REVIEW: self._format_ai_review_message,
        }

    def _get_timestamp(self) -> str:
        """获取格式化时间戳"""
        return datetime.now().strftime("%H:%M:%S")

    def _get_repo_display_name(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> str:
        """获取仓库显示名称"""
        repo_name = payload.get("repository", {}).get("full_name", "Unknown")
        repo_alias = repo_config.get("repo_mappings", {}).get(repo_name, {}).get("alias")
        return repo_alias or repo_name

    def _get_real_pusher(self, payload: Dict[str, Any]) -> str:
        """获取真实的推送者, 避免显示github-actions[bot]"""
        pusher = payload.get("pusher", {}).get("name", "")
        if pusher and pusher != "github-actions[bot]":
            return pusher
        commits = payload.get("commits", [])
        if commits:
            latest_commit = commits[-1] if commits else {}
            author = latest_commit.get("author", {})
            if isinstance(author, dict):
                username = author.get("username")
                if username and username != "github-actions[bot]":
                    return username
                name = author.get("name")
                if name and name != "github-actions[bot]":
                    return name
        sender = payload.get("sender", {}).get("login", "")
        if sender and sender != "github-actions[bot]":
            return sender
        return "自动化"

    def _should_filter_bot_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> bool:
        """检查是否应该过滤bot自身的消息"""
        bot_username = repo_config.get("allow_review", {}).get("bot_username")
        if bot_username:
            sender = payload.get("sender", {}).get("login", "")
            if sender == bot_username:
                return True
        sender = payload.get("sender", {}).get("login", "")
        if sender == "github-actions[bot]":
            logger.debug(f"过滤github-actions[bot]消息: {payload.get('repository', {}).get('full_name', 'Unknown')}")
            return True
        pusher = payload.get("pusher", {}).get("name", "")
        if pusher == "github-actions[bot]":
            logger.debug(f"过滤github-actions[bot]推送: {payload.get('repository', {}).get('full_name', 'Unknown')}")
            return True

        return False

    def _check_star_milestone(self, stargazers_count: int, repo_config: Dict[str, Any]) -> bool:
        """检查是否达到star里程碑"""
        # 从全局配置获取star里程碑设置
        star_milestones = self.global_config.get("star_milestones", {})
        if not star_milestones.get("enabled", False):
            return False
        targets = star_milestones.get("targets", [])
        return stargazers_count in targets

    def _extract_mentions(self, payload: Dict[str, Any]) -> List[str]:
        """从GitHub事件payload中提取需要提及的用户"""
        import re

        mentions = set()  # 使用set避免重复
        text_fields = []

        def collect_text_fields(obj, prefix=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key in [
                        "title",
                        "body",
                        "message",
                        "description",
                        "text",
                        "content",
                    ]:
                        if isinstance(value, str) and value.strip():
                            text_fields.append(value)
                    elif isinstance(value, (dict, list)):
                        collect_text_fields(value, f"{prefix}.{key}" if prefix else key)
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, (dict, list)):
                        collect_text_fields(item, prefix)

        collect_text_fields(payload)
        # 使用正则表达式提取@用户名
        mention_pattern = r"@([a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38})"
        for text in text_fields:
            matches = re.findall(mention_pattern, text)
            for match in matches:
                mentions.add(match)
        user_fields = [
            "sender",
            "pusher",
            "author",
            "committer",
            "user",
            "assignee",
            "requested_reviewer",
            "reviewer",
            "actor",
        ]
        for field in user_fields:
            user_obj = payload.get(field)
            if user_obj and isinstance(user_obj, dict):
                login = user_obj.get("login")
                if login:
                    mentions.add(login)
        # 提取嵌套对象中的用户
        nested_objects = [
            "pull_request",
            "issue",
            "release",
            "comment",
            "review",
            "discussion",
            "milestone",
            "project",
            "team",
            "member",
        ]

        for obj_name in nested_objects:
            obj = payload.get(obj_name)
            if obj and isinstance(obj, dict):
                for field in user_fields:
                    user_obj = obj.get(field)
                    if user_obj and isinstance(user_obj, dict):
                        login = user_obj.get("login")
                        if login:
                            mentions.add(login)
                for array_field in ["assignees", "requested_reviewers"]:
                    users_array = obj.get(array_field, [])
                    if isinstance(users_array, list):
                        for user_obj in users_array:
                            if isinstance(user_obj, dict):
                                login = user_obj.get("login")
                                if login:
                                    mentions.add(login)
        commits = payload.get("commits", [])
        if isinstance(commits, list):
            for commit in commits:
                if isinstance(commit, dict):
                    author = commit.get("author", {})
                    committer = commit.get("committer", {})
                    if isinstance(author, dict) and author.get("username"):
                        username = author["username"]
                        if username != "github-actions[bot]":
                            mentions.add(username)
                    if isinstance(committer, dict) and committer.get("username"):
                        username = committer["username"]
                        if username != "github-actions[bot]":
                            mentions.add(username)
        filtered_mentions = []
        for mention in mentions:
            if mention and mention != "github-actions[bot]" and not mention.endswith("[bot]"):
                filtered_mentions.append(mention)

        return filtered_mentions

    def format_message(
        self,
        message_type: MessageType,
        payload: Dict[str, Any],
        repo_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[MessageContent]:
        """格式化消息内容"""
        if repo_config is None:
            repo_config = {}
        if self._should_filter_bot_message(payload, repo_config):
            logger.debug(f"过滤bot自身消息: {payload.get('sender', {}).get('login', 'Unknown')} - {message_type.value}")
            return None

        formatter = self.formatters.get(message_type)
        if not formatter:
            logger.warning(f"未找到消息类型 {message_type} 的格式化器")
            return self._format_default_message(payload, repo_config)

        try:
            result = formatter(payload, repo_config)
            # 某些格式化器可能返回None(如star里程碑检查、fork/watch禁用)
            return result
        except Exception as e:
            logger.error(f"格式化消息失败: {e}")
            return self._format_error_message(str(e), payload)

    def _format_push_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化推送消息"""
        display_name = self._get_repo_display_name(payload, repo_config)
        icon = EVENT_ICONS.get("push", EVENT_ICONS["default"])
        timestamp = self._get_timestamp()

        ref = payload.get("ref", "")
        branch = ref.split("/")[-1] if ref.startswith("refs/heads/") else ref

        # 获取推送者(优先从commits中获取, 避免github-actions[bot])
        pusher = self._get_real_pusher(payload)
        commits = payload.get("commits", [])
        commit_count = len(commits)
        added = modified = removed = 0
        changed_files = set()  # 用于统计变更的文件

        for commit in commits:
            added += len(commit.get("added", []))
            modified += len(commit.get("modified", []))
            removed += len(commit.get("removed", []))
            changed_files.update(commit.get("added", []))
            changed_files.update(commit.get("modified", []))
            changed_files.update(commit.get("removed", []))

        title = f"{icon} {display_name} ({timestamp}) Push 推送~"
        content_lines = [
            f"├─ 🌿 分支: {branch}",
            f"├─ 👤 By: {pusher}",
            f"├─ 📝 提交数: {commit_count}",
        ]
        if added or modified or removed:
            content_lines.append(f"├─ 📊 变更: +{added} ~{modified} -{removed}")
            file_count = len(changed_files)
            if file_count > 0:
                content_lines.append(f"└─ 📁 文件: {file_count} 个文件变更")
            else:
                content_lines[-1] = content_lines[-1].replace("├─", "└─")
        else:
            content_lines[-1] = content_lines[-1].replace("├─", "└─")

        content = "\n".join(content_lines)
        compare_url = payload.get("compare")
        if compare_url:
            content += f"\n🔗 {compare_url}"

        return MessageContent(
            title=title,
            content=content,
            url=compare_url,
            metadata={
                "commit_count": commit_count,
                "branch": branch,
                "changes": {"added": added, "modified": modified, "removed": removed},
                "files_changed": list(changed_files)[:10],  # 最多保存10个文件名
            },
            mentions=self._extract_mentions(payload),
        )

    def _format_pr_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化PR消息"""
        display_name = self._get_repo_display_name(payload, repo_config)
        icon = EVENT_ICONS.get("pull_request", EVENT_ICONS["default"])
        timestamp = self._get_timestamp()
        action = payload.get("action", "unknown")
        pr = payload.get("pull_request", {})
        pr_number = pr.get("number", "Unknown")
        pr_title = pr.get("title", "No title")
        pr_url = pr.get("html_url", "")
        user = payload.get("sender", {}).get("login", "Unknown")
        if action == "closed" and pr.get("merged", False):
            action_text = "已合并"
        else:
            action_map = {
                "opened": "已创建",
                "closed": "已关闭",
                "reopened": "已重开",
                "edited": "已编辑",
                "ready_for_review": "准备审查",
                "review_requested": "请求审查",
                "labeled": "已添加标签",
                "unlabeled": "已移除标签",
                "synchronize": "已同步",
            }
            action_text = action_map.get(action, action)
        title = f"{icon} {display_name} ({timestamp}) PR {action_text}~"
        content_lines = [f"├─ 🆔 #{pr_number}", f'├─ 📝 标题: "{pr_title}"']
        if action in ["labeled", "unlabeled"]:
            label = payload.get("label", {})
            label_name = label.get("name", "Unknown")
            label_color = label.get("color", "")
            content_lines.append(f"├─ 🏷️ 标签: {label_name} (#{label_color if label_color else ''})")
        content_lines.append(f"└─ 👤 By: {user}")
        content = "\n".join(content_lines)
        if pr_url:
            content += f"\n🔗 {pr_url}"

        if action == "review_requested":
            reviewer_login = payload.get("requested_reviewer", {}).get("login", "Unknown") or pr.get(
                "requested_reviewers", [{}]
            )[0].get("login", "Unknown")
            content_lines = [
                f"├─ 🆔 #{pr_number}",
                f'├─ 📝 标题: "{pr_title}"',
                f"├─ 👤 请求者: {user}",
                f"└─ 🔍 审查者: {reviewer_login}",
            ]
            content = "\n".join(content_lines)
            if pr_url:
                content += f"\n🔗 {pr_url}"

        return MessageContent(
            title=title,
            content=content,
            url=pr_url,
            metadata={
                "pr_number": pr_number,
                "action": action,
                "merged": pr.get("merged", False),
            },
            mentions=self._extract_mentions(payload),
        )

    def _format_issues_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化Issues消息"""
        display_name = self._get_repo_display_name(payload, repo_config)
        icon = EVENT_ICONS.get("issues", EVENT_ICONS["default"])
        timestamp = self._get_timestamp()
        action = payload.get("action", "unknown")
        issue = payload.get("issue", {})
        issue_number = issue.get("number", "Unknown")
        issue_title = issue.get("title", "No title")
        issue_url = issue.get("html_url", "")
        user = payload.get("sender", {}).get("login", "Unknown")
        action_map = {
            "opened": "已创建",
            "closed": "已关闭",
            "reopened": "已重开",
            "edited": "已编辑",
            "assigned": "已分配",
            "unassigned": "已取消分配",
            "labeled": "已添加标签",
            "unlabeled": "已移除标签",
        }
        action_text = action_map.get(action, action)
        title = f"{icon} {display_name} ({timestamp}) Issue {action_text}~"
        content_lines = [f"├─ 🆔 #{issue_number}", f'├─ 📝 标题: "{issue_title}"']
        if action in ["labeled", "unlabeled"]:
            label = payload.get("label", {})
            label_name = label.get("name", "Unknown")
            label_color = label.get("color", "")
            if label_color:
                content_lines.append(f"├─ 🏷️ 标签: {label_name} (#{label_color})")
            else:
                content_lines.append(f"├─ 🏷️ 标签: {label_name}")
        content_lines.append(f"└─ 👤 By: {user}")
        content = "\n".join(content_lines)
        if issue_url:
            content += f"\n🔗 {issue_url}"

        return MessageContent(
            title=title,
            content=content,
            url=issue_url,
            metadata={"issue_number": issue_number, "action": action},
            mentions=self._extract_mentions(payload),
        )

    def _format_release_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化发布消息"""
        display_name = self._get_repo_display_name(payload, repo_config)
        icon = EVENT_ICONS.get("release", EVENT_ICONS["default"])
        timestamp = self._get_timestamp()
        action = payload.get("action", "unknown")
        release = payload.get("release", {})
        tag_name = release.get("tag_name", "Unknown")
        release_name = release.get("name", tag_name)
        release_url = release.get("html_url", "")
        user = payload.get("sender", {}).get("login", "Unknown")
        action_text = "已发布" if action == "published" else action
        title = f"{icon} {display_name} ({timestamp}) Release {action_text}~"
        content_lines = [f"├─ 🏷️ 版本: {tag_name}"]
        if release_name != tag_name:
            content_lines.append(f'├─ 📋 名称: "{release_name}"')
        content_lines.append(f"└─ 👤 By: {user}")
        content = "\n".join(content_lines)
        if release_url:
            content += f"\n🔗 {release_url}"

        return MessageContent(
            title=title,
            content=content,
            url=release_url,
            metadata={
                "tag_name": tag_name,
                "action": action,
                "prerelease": release.get("prerelease", False),
            },
            mentions=self._extract_mentions(payload),
        )

    def _format_star_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> Optional[MessageContent]:
        """格式化星标消息(仅里程碑通知)"""
        action = payload.get("action", "unknown")
        stargazers_count = payload.get("repository", {}).get("stargazers_count", 0)
        if action != "created" or not self._check_star_milestone(stargazers_count, self.global_config):
            return None

        display_name = self._get_repo_display_name(payload, repo_config)
        icon = EVENT_ICONS.get("star", EVENT_ICONS["default"])
        timestamp = self._get_timestamp()
        user = payload.get("sender", {}).get("login", "Unknown")
        repo_url = payload.get("repository", {}).get("html_url", "")

        title = f"{icon} {display_name} ({timestamp}) 🎉 达成 {stargazers_count} Stars 里程碑！"
        content_lines = [
            f"├─ 🎯 里程碑: {stargazers_count} ⭐",
            f"├─ 👤 感谢: @{user}",
        ]

        content = "\n".join(content_lines)
        if repo_url:
            content += f"\n🔗 {repo_url}"

        return MessageContent(
            title=title,
            content=content,
            url=repo_url,
            metadata={
                "action": action,
                "stargazers_count": stargazers_count,
                "milestone": True,
            },
            mentions=self._extract_mentions(payload),
        )

    def _format_fork_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> Optional[MessageContent]:
        """格式化Fork消息"""
        logger.debug(
            f"Fork事件已记录: {payload.get('sender', {}).get('login', 'Unknown')} forked {payload.get('repository', {}).get('full_name', 'Unknown')}"
        )
        return None

    def _format_watch_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> Optional[MessageContent]:
        """格式化Watch消息"""
        logger.debug(
            f"Watch事件已记录: {payload.get('sender', {}).get('login', 'Unknown')} {payload.get('action', 'unknown')} watching {payload.get('repository', {}).get('full_name', 'Unknown')}"
        )
        return None

    def _format_create_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化创建事件消息"""
        ref_type = payload.get("ref_type", "")
        ref = payload.get("ref", "")
        repo_name = payload.get("repository", {}).get("full_name", "Unknown")
        sender = payload.get("sender", {}).get("login", "Unknown")
        repo_url = payload.get("repository", {}).get("html_url", "")
        type_emoji = {"branch": "🌿", "tag": "🏷️", "repository": "📁"}.get(ref_type, "🆕")
        title = f"{type_emoji} {repo_name} - 创建了{ref_type}"

        content_lines = [
            f"👤 创建者: {sender}",
            f"📝 类型: {ref_type}",
            f"🎯 名称: {ref}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=repo_url,
            metadata={"ref_type": ref_type, "ref": ref},
        )

    def _format_delete_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化删除事件消息"""
        ref_type = payload.get("ref_type", "")
        ref = payload.get("ref", "")
        repo_name = payload.get("repository", {}).get("full_name", "Unknown")
        sender = payload.get("sender", {}).get("login", "Unknown")
        repo_url = payload.get("repository", {}).get("html_url", "")
        type_emoji = {"branch": "🌿", "tag": "🏷️"}.get(ref_type, "🗑️")
        title = f"{type_emoji} {repo_name} - 删除了{ref_type}"
        content_lines = [
            f"👤 删除者: {sender}",
            f"📝 类型: {ref_type}",
            f"🎯 名称: {ref}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=repo_url,
            metadata={"ref_type": ref_type, "ref": ref},
        )

    def _format_workflow_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化工作流消息"""
        workflow_run = payload.get("workflow_run", {})
        repo_name = payload.get("repository", {}).get("full_name", "Unknown")
        workflow_name = workflow_run.get("name", "Unknown")
        status = workflow_run.get("status", "")
        conclusion = workflow_run.get("conclusion", "")
        actor = workflow_run.get("actor", {}).get("login", "Unknown")
        branch = workflow_run.get("head_branch", "Unknown")
        workflow_url = workflow_run.get("html_url", "")
        # 状态
        if conclusion == "success":
            emoji = "✅"
            status_text = "成功"
        elif conclusion == "failure":
            emoji = "❌"
            status_text = "失败"
        elif conclusion == "cancelled":
            emoji = "⏹️"
            status_text = "已取消"
        elif status == "in_progress":
            emoji = "🔄"
            status_text = "运行中"
        else:
            emoji = "⚪"
            status_text = status or conclusion or "未知"

        title = f"{emoji} {repo_name} - 工作流 {status_text}"
        content_lines = [
            f"👤 触发者: {actor}",
            f"🔧 工作流: {workflow_name}",
            f"🌿 分支: {branch}",
            f"📊 状态: {status_text}",
        ]
        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=workflow_url,
            metadata={
                "workflow_name": workflow_name,
                "status": status,
                "conclusion": conclusion,
            },
            mentions=self._extract_mentions(payload),
        )

    def _format_system_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化系统消息"""
        message = payload.get("message", "Unknown")
        level = payload.get("level", "info")
        source = payload.get("source", "System")

        level_emoji = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "success": "✅"}.get(level, "ℹ️")
        title = f"{level_emoji} 系统消息 - {level.title()}"
        content_lines = [f"📡 来源: {source}", f"📝 消息: {message}"]
        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            metadata={"level": level, "source": source},
        )

    def _format_default_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化默认消息"""
        event_type = payload.get("event_type", "unknown")
        user = payload.get("sender", {}).get("login", "Unknown")
        repo_name = payload.get("repository", {}).get("full_name", "Unknown")
        action = payload.get("action")
        logger.warning(f"未知GitHub事件: {event_type} | 仓库: {repo_name} | 用户: {user} | 动作: {action}")
        logger.debug(f"未知事件详细payload: {json.dumps(payload, indent=2, ensure_ascii=False)[:1000]}")
        display_name = self._get_repo_display_name(payload, repo_config)
        icon = EVENT_ICONS.get("default", "📢")
        timestamp = self._get_timestamp()
        repo_url = payload.get("repository", {}).get("html_url", "")
        title = f"{icon} {display_name} ({timestamp}) {event_type}~"
        content_lines = [f"├─ 👤 By: {user}"]

        if action:
            content_lines.append(f"├─ 🔧 Action: {action}")
            content_lines.append(f"└─ 📝 Event: {event_type}")
        else:
            content_lines.append(f"└─ 📝 Event: {event_type}")
        content = "\n".join(content_lines)
        if repo_url:
            content += f"\n🔗 {repo_url}"

        return MessageContent(
            title=title,
            content=content,
            url=repo_url,
            metadata={"event_type": event_type, "action": action},
            mentions=self._extract_mentions(payload),
        )

    def _format_error_message(self, error: str, payload: Dict[str, Any]) -> MessageContent:
        """格式化错误消息"""
        return MessageContent(
            title="❌ 消息格式化错误",
            content=f"格式化消息时发生错误: {error}",
            metadata={"error": error, "raw_payload": payload},
            mentions=self._extract_mentions(payload),
        )

    def _format_commit_comment_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化提交评论消息"""
        comment = payload.get("comment", {})
        commit = payload.get("comment", {}).get("commit_id", "")
        payload.get("repository", {}).get("full_name", "Unknown")
        user = payload.get("sender", {}).get("login", "Unknown")
        comment_body = comment.get("body", "")[:100] + ("..." if len(comment.get("body", "")) > 100 else "")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        title = f"💬 {display_name} ({timestamp}) 提交评论"
        content_lines = [
            f"├─ 👤 评论者: {user}",
            f"├─ 📝 提交: {commit[:8]}",
            f"└─ 💬 内容: {comment_body}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=comment.get("html_url", ""),
            metadata={"commit_id": commit, "comment_id": comment.get("id")},
        )

    def _format_discussion_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化讨论消息"""
        discussion = payload.get("discussion", {})
        action = payload.get("action", "")
        payload.get("repository", {}).get("full_name", "Unknown")
        user = payload.get("sender", {}).get("login", "Unknown")
        title_text = discussion.get("title", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        action_text = {
            "created": "创建了讨论",
            "edited": "编辑了讨论",
            "deleted": "删除了讨论",
            "answered": "回答了讨论",
            "unanswered": "取消回答讨论",
        }.get(action, f"{action}讨论")

        title = f"💭 {display_name} ({timestamp}) {action_text}"
        content_lines = [
            f"├─ 👤 用户: {user}",
            f"├─ 🔧 动作: {action_text}",
            f"└─ 📝 标题: {title_text}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=discussion.get("html_url", ""),
            metadata={"discussion_id": discussion.get("id"), "action": action},
        )

    def _format_gollum_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化Wiki页面消息"""
        pages = payload.get("pages", [])
        payload.get("repository", {}).get("full_name", "Unknown")
        user = payload.get("sender", {}).get("login", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        if pages:
            page = pages[0]
            page_name = page.get("page_name", "Unknown")
            action = page.get("action", "edited")
            action_text = {"created": "创建", "edited": "编辑"}.get(action, action)

            title = f"📖 {display_name} ({timestamp}) Wiki {action_text}"
            content_lines = [
                f"├─ 👤 编辑者: {user}",
                f"├─ 🔧 动作: {action_text}",
                f"└─ 📄 页面: {page_name}",
            ]

            if len(pages) > 1:
                content_lines.append(f"📊 共 {len(pages)} 个页面被修改")
        else:
            title = f"📖 {display_name} ({timestamp}) Wiki更新"
            content_lines = [f"├─ 👤 编辑者: {user}", f"└─ 📄 Wiki页面已更新"]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=payload.get("repository", {}).get("html_url", "") + "/wiki",
            metadata={"pages_count": len(pages)},
        )

    def _format_member_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化成员管理消息"""
        action = payload.get("action", "")
        member = payload.get("member", {})
        payload.get("repository", {}).get("full_name", "Unknown")
        sender = payload.get("sender", {}).get("login", "Unknown")
        member_login = member.get("login", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        action_text = {
            "added": "添加了成员",
            "removed": "移除了成员",
            "edited": "编辑了成员权限",
        }.get(action, f"{action}成员")

        title = f"👥 {display_name} ({timestamp}) {action_text}"
        content_lines = [
            f"├─ 👤 操作者: {sender}",
            f"├─ 🔧 动作: {action_text}",
            f"└─ 👤 成员: {member_login}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=payload.get("repository", {}).get("html_url", ""),
            metadata={"action": action, "member": member_login},
        )

    def _format_membership_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化团队成员消息"""
        action = payload.get("action", "")
        member = payload.get("member", {})
        team = payload.get("team", {})
        payload.get("sender", {}).get("login", "Unknown")
        member_login = member.get("login", "Unknown")
        team_name = team.get("name", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        action_text = {"added": "加入了团队", "removed": "离开了团队"}.get(action, f"{action}团队")

        title = f"🏢 {display_name} ({timestamp}) 团队成员变更"
        content_lines = [
            f"├─ 👤 成员: {member_login}",
            f"├─ 🔧 动作: {action_text}",
            f"└─ 👥 团队: {team_name}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=team.get("html_url", ""),
            metadata={"action": action, "member": member_login, "team": team_name},
        )

    def _format_milestone_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化里程碑消息"""
        action = payload.get("action", "")
        milestone = payload.get("milestone", {})
        payload.get("repository", {}).get("full_name", "Unknown")
        sender = payload.get("sender", {}).get("login", "Unknown")
        milestone_title = milestone.get("title", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        action_text = {
            "created": "创建了里程碑",
            "closed": "关闭了里程碑",
            "opened": "重新打开里程碑",
            "edited": "编辑了里程碑",
            "deleted": "删除了里程碑",
        }.get(action, f"{action}里程碑")

        title = f"🎯 {display_name} ({timestamp}) {action_text}"
        content_lines = [
            f"├─ 👤 操作者: {sender}",
            f"├─ 🔧 动作: {action_text}",
            f"└─ 📝 标题: {milestone_title}",
        ]

        if action in ["created", "opened", "edited"]:
            open_issues = milestone.get("open_issues", 0)
            closed_issues = milestone.get("closed_issues", 0)
            total_issues = open_issues + closed_issues
            if total_issues > 0:
                progress = int((closed_issues / total_issues) * 100)
                content_lines.append(f"📊 进度: {progress}% ({closed_issues}/{total_issues})")

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=milestone.get("html_url", ""),
            metadata={"action": action, "milestone_id": milestone.get("id")},
        )

    def _format_project_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化项目消息"""
        action = payload.get("action", "")
        project = payload.get("project", {})
        sender = payload.get("sender", {}).get("login", "Unknown")
        project_name = project.get("name", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        action_text = {
            "created": "创建了项目",
            "edited": "编辑了项目",
            "closed": "关闭了项目",
            "reopened": "重新打开项目",
            "deleted": "删除了项目",
        }.get(action, f"{action}项目")

        title = f"📊 {display_name} ({timestamp}) {action_text}"
        content_lines = [
            f"├─ 👤 操作者: {sender}",
            f"├─ 🔧 动作: {action_text}",
            f"└─ 📝 项目: {project_name}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=project.get("html_url", ""),
            metadata={"action": action, "project_id": project.get("id")},
        )

    def _format_project_card_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化项目卡片消息"""
        action = payload.get("action", "")
        project_card = payload.get("project_card", {})
        sender = payload.get("sender", {}).get("login", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        action_text = {
            "created": "创建了卡片",
            "edited": "编辑了卡片",
            "moved": "移动了卡片",
            "converted": "转换了卡片",
            "deleted": "删除了卡片",
        }.get(action, f"{action}卡片")

        title = f"🃏 {display_name} ({timestamp}) 项目{action_text}"
        content_lines = [
            f"├─ 👤 操作者: {sender}",
            f"├─ 🔧 动作: {action_text}",
            f"└─ 🃏 卡片ID: {project_card.get('id', 'Unknown')}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=project_card.get("url", ""),
            metadata={"action": action, "card_id": project_card.get("id")},
        )

    def _format_project_column_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化项目列消息"""
        action = payload.get("action", "")
        project_column = payload.get("project_column", {})
        sender = payload.get("sender", {}).get("login", "Unknown")
        column_name = project_column.get("name", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        action_text = {
            "created": "创建了列",
            "edited": "编辑了列",
            "moved": "移动了列",
            "deleted": "删除了列",
        }.get(action, f"{action}列")

        title = f"📋 {display_name} ({timestamp}) 项目{action_text}"
        content_lines = [
            f"├─ 👤 操作者: {sender}",
            f"├─ 🔧 动作: {action_text}",
            f"└─ 📋 列名: {column_name}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=project_column.get("url", ""),
            metadata={"action": action, "column_id": project_column.get("id")},
        )

    def _format_public_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化仓库公开消息"""
        payload.get("repository", {}).get("full_name", "Unknown")
        sender = payload.get("sender", {}).get("login", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        title = f"🌍 {display_name} ({timestamp}) 仓库已公开"
        content_lines = [f"├─ 👤 操作者: {sender}", f"└─ 🌍 仓库现在对所有人可见"]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=payload.get("repository", {}).get("html_url", ""),
            metadata={"action": "made_public"},
        )

    def _format_pr_review_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化PR审查消息"""
        action = payload.get("action", "")
        review = payload.get("review", {})
        pull_request = payload.get("pull_request", {})
        reviewer = review.get("user", {}).get("login", "Unknown")
        pr_number = pull_request.get("number", 0)
        pr_title = pull_request.get("title", "Unknown")
        review_state = review.get("state", "")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        state_emoji = {
            "approved": "✅",
            "changes_requested": "❌",
            "commented": "💬",
        }.get(review_state, "👁️")

        state_text = {
            "approved": "批准了",
            "changes_requested": "请求修改",
            "commented": "评论了",
        }.get(review_state, "审查了")

        title = f"👁️ {display_name} ({timestamp}) PR审查"
        content_lines = [
            f"├─ 👤 审查者: {reviewer}",
            f"├─ {state_emoji} 结果: {state_text}",
            f"└─ 🔀 PR: #{pr_number} {pr_title}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=review.get("html_url", ""),
            metadata={
                "action": action,
                "review_state": review_state,
                "pr_number": pr_number,
            },
        )

    def _format_pr_review_comment_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化PR审查评论消息"""
        action = payload.get("action", "")
        comment = payload.get("comment", {})
        pull_request = payload.get("pull_request", {})
        commenter = comment.get("user", {}).get("login", "Unknown")
        pr_number = pull_request.get("number", 0)
        pr_title = pull_request.get("title", "Unknown")
        comment_body = comment.get("body", "")[:100] + ("..." if len(comment.get("body", "")) > 100 else "")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        action_text = {
            "created": "添加了审查评论",
            "edited": "编辑了审查评论",
            "deleted": "删除了审查评论",
        }.get(action, f"{action}审查评论")

        title = f"💬 {display_name} ({timestamp}) {action_text}"
        content_lines = [
            f"├─ 👤 评论者: {commenter}",
            f"├─ 🔀 PR: #{pr_number} {pr_title}",
            f"└─ 💬 内容: {comment_body}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=comment.get("html_url", ""),
            metadata={
                "action": action,
                "pr_number": pr_number,
                "comment_id": comment.get("id"),
            },
        )

    def _format_repository_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化仓库事件消息"""
        action = payload.get("action", "")
        repository = payload.get("repository", {})
        sender = payload.get("sender", {}).get("login", "Unknown")
        repo_name = repository.get("full_name", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        action_text = {
            "created": "创建了仓库",
            "deleted": "删除了仓库",
            "archived": "归档了仓库",
            "unarchived": "取消归档仓库",
            "publicized": "公开了仓库",
            "privatized": "私有化了仓库",
            "transferred": "转移了仓库",
        }.get(action, f"{action}仓库")

        title = f"📁 {display_name} ({timestamp}) {action_text}"
        content_lines = [
            f"├─ 👤 操作者: {sender}",
            f"├─ 🔧 动作: {action_text}",
            f"└─ 📁 仓库: {repo_name}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=repository.get("html_url", ""),
            metadata={"action": action, "repo_id": repository.get("id")},
        )

    def _format_status_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化状态检查消息"""
        state = payload.get("state", "")
        context = payload.get("context", "Unknown")
        description = payload.get("description", "")
        commit = payload.get("commit", {})
        commit_sha = commit.get("sha", "")[:8]

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        state_emoji = {
            "success": "✅",
            "failure": "❌",
            "error": "🚨",
            "pending": "🔄",
        }.get(state, "📊")

        title = f"📊 {display_name} ({timestamp}) 状态检查"
        content_lines = [
            f"├─ {state_emoji} 状态: {state}",
            f"├─ 🔧 检查: {context}",
            f"├─ 📝 提交: {commit_sha}",
            f"└─ 💬 描述: {description}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=payload.get("target_url", ""),
            metadata={"state": state, "context": context, "commit_sha": commit_sha},
        )

    def _format_team_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化团队消息"""
        action = payload.get("action", "")
        team = payload.get("team", {})
        sender = payload.get("sender", {}).get("login", "Unknown")
        team_name = team.get("name", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        action_text = {
            "created": "创建了团队",
            "deleted": "删除了团队",
            "edited": "编辑了团队",
            "added_to_repository": "添加到仓库",
            "removed_from_repository": "从仓库移除",
        }.get(action, f"{action}团队")

        title = f"👥 {display_name} ({timestamp}) {action_text}"
        content_lines = [
            f"├─ 👤 操作者: {sender}",
            f"├─ 🔧 动作: {action_text}",
            f"└─ 👥 团队: {team_name}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=team.get("html_url", ""),
            metadata={"action": action, "team_id": team.get("id")},
        )

    def _format_team_add_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化团队添加消息"""
        team = payload.get("team", {})
        repository = payload.get("repository", {})
        team_name = team.get("name", "Unknown")
        repo_name = repository.get("full_name", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        title = f"➕ {display_name} ({timestamp}) 团队权限授予"
        content_lines = [
            f"├─ 👥 团队: {team_name}",
            f"├─ 📁 仓库: {repo_name}",
            f"└─ ✅ 团队已获得仓库访问权限",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=repository.get("html_url", ""),
            metadata={"team_id": team.get("id"), "repo_id": repository.get("id")},
        )

    def _format_check_run_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化检查运行消息"""
        action = payload.get("action", "")
        check_run = payload.get("check_run", {})
        name = check_run.get("name", "Unknown")
        status = check_run.get("status", "")
        conclusion = check_run.get("conclusion", "")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()
        # 状态
        if conclusion == "success":
            emoji = "✅"
            status_text = "成功"
        elif conclusion == "failure":
            emoji = "❌"
            status_text = "失败"
        elif conclusion == "cancelled":
            emoji = "⏹️"
            status_text = "已取消"
        elif status == "in_progress":
            emoji = "🔄"
            status_text = "运行中"
        else:
            emoji = "✅"
            status_text = status or conclusion or "未知"

        title = f"✅ {display_name} ({timestamp}) 检查运行"
        content_lines = [
            f"├─ {emoji} 状态: {status_text}",
            f"├─ 🔧 检查: {name}",
            f"└─ 🔧 动作: {action}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=check_run.get("html_url", ""),
            metadata={"action": action, "status": status, "conclusion": conclusion},
        )

    def _format_check_suite_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化检查套件消息"""
        action = payload.get("action", "")
        check_suite = payload.get("check_suite", {})
        status = check_suite.get("status", "")
        conclusion = check_suite.get("conclusion", "")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        # 状态表情
        if conclusion == "success":
            emoji = "✅"
            status_text = "成功"
        elif conclusion == "failure":
            emoji = "❌"
            status_text = "失败"
        elif status == "in_progress":
            emoji = "🔄"
            status_text = "运行中"
        else:
            emoji = "📋"
            status_text = status or conclusion or "未知"

        title = f"📋 {display_name} ({timestamp}) 检查套件"
        content_lines = [
            f"├─ {emoji} 状态: {status_text}",
            f"├─ 🔧 动作: {action}",
            f"└─ 📋 套件ID: {check_suite.get('id', 'Unknown')}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=check_suite.get("url", ""),
            metadata={"action": action, "status": status, "conclusion": conclusion},
        )

    def _format_deployment_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化部署消息"""
        deployment = payload.get("deployment", {})
        sender = payload.get("sender", {}).get("login", "Unknown")
        environment = deployment.get("environment", "Unknown")
        ref = deployment.get("ref", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        title = f"🚀 {display_name} ({timestamp}) 部署创建"
        content_lines = [
            f"├─ 👤 部署者: {sender}",
            f"├─ 🌍 环境: {environment}",
            f"├─ 🌿 分支: {ref}",
            f"└─ 🚀 部署已创建",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=deployment.get("url", ""),
            metadata={
                "environment": environment,
                "ref": ref,
                "deployment_id": deployment.get("id"),
            },
        )

    def _format_deployment_status_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化部署状态消息"""
        deployment_status = payload.get("deployment_status", {})
        deployment = payload.get("deployment", {})
        state = deployment_status.get("state", "")
        environment = deployment.get("environment", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        state_emoji = {
            "success": "✅",
            "failure": "❌",
            "error": "🚨",
            "pending": "🔄",
            "in_progress": "🔄",
        }.get(state, "📊")

        state_text = {
            "success": "成功",
            "failure": "失败",
            "error": "错误",
            "pending": "等待中",
            "in_progress": "进行中",
        }.get(state, state)

        title = f"📊 {display_name} ({timestamp}) 部署状态"
        content_lines = [
            f"├─ {state_emoji} 状态: {state_text}",
            f"├─ 🌍 环境: {environment}",
            f"└─ 🚀 部署ID: {deployment.get('id', 'Unknown')}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=deployment_status.get("target_url", ""),
            metadata={
                "state": state,
                "environment": environment,
                "deployment_id": deployment.get("id"),
            },
        )

    def _format_page_build_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化页面构建消息"""
        build = payload.get("build", {})
        pusher = build.get("pusher", {}).get("login", "Unknown")
        status = build.get("status", "")
        error = build.get("error", {})

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        if status == "built":
            emoji = "✅"
            status_text = "构建成功"
        elif error.get("message"):
            emoji = "❌"
            status_text = "构建失败"
        else:
            emoji = "📄"
            status_text = "页面构建"

        title = f"📄 {display_name} ({timestamp}) {status_text}"
        content_lines = [f"├─ 👤 推送者: {pusher}", f"├─ {emoji} 状态: {status_text}"]

        if error.get("message"):
            content_lines.append(f"└─ ❌ 错误: {error.get('message', '')[:100]}")
        else:
            content_lines.append(f"└─ 📄 GitHub Pages 已更新")

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=build.get("url", ""),
            metadata={"status": status, "build_id": build.get("id")},
        )

    def _format_ping_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化Ping消息"""
        zen = payload.get("zen", "GitHub is awesome!")
        hook_id = payload.get("hook_id", "Unknown")
        sender = payload.get("sender", {}).get("login", "Unknown")

        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()

        title = f"🏓 {display_name} ({timestamp}) Webhook测试"
        content_lines = [
            f"├─ 👤 发送者: {sender}",
            f"├─ 🔗 Hook ID: {hook_id}",
            f"└─ 💭 禅语: {zen}",
        ]

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=payload.get("repository", {}).get("html_url", ""),
            metadata={"hook_id": hook_id, "zen": zen},
        )

    def _format_ai_review_message(self, payload: Dict[str, Any], repo_config: Dict[str, Any]) -> MessageContent:
        """格式化代码审查消息"""
        pr_number = payload.get("pr_number", "Unknown")
        repository_name = payload.get("repository", {}).get("full_name", "Unknown")
        review_summary = payload.get("review_summary", "AI代码审查已完成")
        review_status = payload.get("review_status", "completed")
        display_name = self._get_repo_display_name(payload, repo_config)
        timestamp = self._get_timestamp()
        status_icon = "✅" if review_status == "approved" else "⚠️" if review_status == "changes_requested" else "🤖"
        title = f"{status_icon} {display_name} ({timestamp}) AI代码审查"
        content_lines = [
            f"├─ 🔍 PR编号: #{pr_number}",
            f"├─ 📊 审查状态: {review_status}",
            f"└─ 📝 审查摘要: {review_summary}",
        ]
        metadata = {
            "pr_number": pr_number,
            "review_status": review_status,
            "review_summary": review_summary,
        }
        if "review_details" in payload:
            details = payload["review_details"]
            if isinstance(details, list) and details:
                content_lines.append("")
                content_lines.append("📋 审查详情:")
                for i, detail in enumerate(details[:3]):  # 最多显示3条详情
                    content_lines.append(f"  {i+1}. {detail}")
                if len(details) > 3:
                    content_lines.append(f"  ... 还有 {len(details)-3} 条建议")

        return MessageContent(
            title=title,
            content="\n".join(content_lines),
            url=payload.get("pr_url", payload.get("repository", {}).get("html_url", "")),
            metadata=metadata,
        )


class MessageRequestProcessor:
    """消息请求处理器"""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        global_config = config_manager.get_global_config() if hasattr(config_manager, "get_global_config") else {}
        self.formatter = MessageFormatter(global_config)
        self.platform_handlers = {}
        self._register_platform_handlers()

    def _register_platform_handlers(self):
        """注册平台处理器"""
        # 这里将其他模块调用register_platform_handler来注册

    def register_platform_handler(self, platform: MessagePlatform, handler_func):
        """注册平台处理器"""
        self.platform_handlers[platform] = handler_func
        logger.success(f"注册消息平台处理器: {platform.value}")

    def get_notification_targets(self, repo_name: str, message_type: MessageType) -> List[NotificationTarget]:
        """获取通知目标列表"""
        targets = []

        try:
            repo_config = self.config_manager.get_repository_config(repo_name)
            if not repo_config:
                logger.warning(f"未找到仓库 {repo_name} 的配置")
                return targets
            notification_channels = repo_config.get("notification_channels", [])
            if "qq" not in notification_channels:
                logger.debug(f"仓库 {repo_name} 未启用qq")
                return targets
            qq_group_ids = repo_config.get("qq_group_ids", repo_config.get("group_ids", []))

            if not qq_group_ids:
                logger.debug(f"仓库 {repo_name} 未配置QQ群组")
                return targets
            for group_id in qq_group_ids:
                target = NotificationTarget(
                    platform=MessagePlatform.QQ,
                    target_id=str(group_id),
                    config={"type": "group", "target_id": str(group_id)},
                )
                targets.append(target)
                logger.debug(f"添加QQ群通知目标: {group_id}")

        except Exception as e:
            logger.error(f"获取通知目标失败: {e}")

        return targets

    def create_message_request(
        self,
        message_type: MessageType,
        payload: Dict[str, Any],
        repo_name: Optional[str] = None,
    ) -> Optional[MessageRequest]:
        """创建消息请求"""
        try:
            # 如果没有提供仓库名, 尝试从payload中提取
            if not repo_name:
                repo_name = payload.get("repository", {}).get("full_name")

            if not repo_name:
                logger.warning("无法确定仓库名称")
                return None
            repo_config = self.config_manager.get_repository_config(repo_name)
            content = self.formatter.format_message(message_type, payload, repo_config)
            if content is None:
                logger.debug(f"消息被过滤或禁用: {message_type.value} - {repo_name}")
                return None
            targets = self.get_notification_targets(repo_name, message_type)

            if not targets:
                logger.info(f"仓库 {repo_name} 的 {message_type.value} 事件没有配置通知目标")
                return None
            message_request = MessageRequest(
                message_type=message_type,
                content=content,
                targets=targets,
                priority=self._get_message_priority(message_type, payload),
            )

            logger.info(f"创建消息请求: {message_type.value} -> {len(targets)} 个目标")
            return message_request

        except Exception as e:
            logger.error(f"创建消息请求失败: {e}")
            return None

    def _get_message_priority(self, message_type: MessageType, payload: Dict[str, Any]) -> int:
        """获取消息优先级"""
        base_priority = {
            MessageType.SYSTEM: 9,
            MessageType.AI_REVIEW: 8,
            MessageType.RELEASE: 7,
            MessageType.PULL_REQUEST: 6,
            MessageType.ISSUES: 5,
            MessageType.WORKFLOW: 4,
            MessageType.PUSH: 3,
            MessageType.STAR: 2,
            MessageType.FORK: 2,
            MessageType.WATCH: 1,
            MessageType.CREATE: 1,
            MessageType.DELETE: 1,
        }.get(message_type, 5)

        if message_type == MessageType.PULL_REQUEST:
            action = payload.get("action", "")
            if action in ["opened", "closed"]:
                base_priority += 1

        elif message_type == MessageType.ISSUES:
            action = payload.get("action", "")
            if action in ["opened", "closed"]:
                base_priority += 1

        elif message_type == MessageType.WORKFLOW:
            conclusion = payload.get("workflow_run", {}).get("conclusion", "")
            if conclusion == "failure":
                base_priority += 2

        return min(base_priority, 10)  # 最大优先级为10

    async def process_message_request(self, message_request: MessageRequest) -> bool:
        """处理消息请求(使用消息聚合器)"""
        try:
            from . import get_bot

            webhook_bot = get_bot()

            if webhook_bot and hasattr(webhook_bot, "msg_aggregator") and webhook_bot.msg_aggregator:
                success_count = 0
                total_count = len(message_request.targets)

                for target in message_request.targets:
                    try:
                        handler = self.platform_handlers.get(target.platform)
                        if not handler:
                            logger.warning(f"未找到平台 {target.platform.value} 的处理器")
                            continue
                        aggregation_key = f"{target.platform.value}_{target.target_id}"
                        await webhook_bot.msg_aggregator.add_message(aggregation_key, message_request.content, [target])
                        success_count += 1
                        logger.debug(f"消息已添加到聚合器: {target.platform.value} -> {target.target_id}")

                    except Exception as e:
                        logger.error(f"添加消息到聚合器异常: {target.platform.value} -> {target.target_id}, 错误: {e}")

                success = success_count > 0
                if success:
                    logger.info(f"消息聚合处理完成: {success_count}/{total_count} 个目标已添加到聚合器")
                else:
                    logger.error(f"消息聚合处理失败: 所有目标都失败")

                return success
            else:
                logger.warning("消息聚合器不可用")
                return await self._process_message_request_direct(message_request)

        except Exception as e:
            logger.error(f"处理消息请求异常: {e}")
            # 回退到直接发送
            return await self._process_message_request_direct(message_request)

    async def _process_message_request_direct(self, message_request: MessageRequest) -> bool:
        """直接处理消息请求(不使用聚合器)"""
        from . import get_bot

        webhook_bot = get_bot()
        if webhook_bot and hasattr(webhook_bot, "msg_aggregator") and webhook_bot.msg_aggregator:
            if webhook_bot.msg_aggregator.is_muted():
                remaining = webhook_bot.msg_aggregator.get_mute_remaining()
                logger.debug(f"处于禁言状态, 跳过直接发送消息。剩余时间: {remaining:.1f}秒")
                return False

        success_count = 0
        total_count = len(message_request.targets)

        for target in message_request.targets:
            try:
                handler = self.platform_handlers.get(target.platform)
                if not handler:
                    logger.warning(f"未找到平台 {target.platform.value} 的处理器")
                    continue
                success = await handler(message_request.content, target)

                if success:
                    success_count += 1
                    logger.debug(f"消息发送成功: {target.platform.value} -> {target.target_id}")
                else:
                    logger.warning(f"消息发送失败: {target.platform.value} -> {target.target_id}")

            except Exception as e:
                logger.error(f"处理消息目标异常: {target.platform.value} -> {target.target_id}, 错误: {e}")

        success = success_count > 0
        if success:
            logger.info(f"消息处理完成: {success_count}/{total_count} 个目标成功")
        else:
            logger.error(f"消息处理失败: 所有目标都失败")

        return success


# 全局消息请求处理器实例
_message_processor = None


def get_message_processor(config_manager) -> MessageRequestProcessor:
    """获取全局消息请求处理器实例"""
    global _message_processor
    if _message_processor is None:
        _message_processor = MessageRequestProcessor(config_manager)
    return _message_processor


def cleanup_message_processor():
    """清理消息处理器资源"""
    global _message_processor
    if _message_processor:
        _message_processor = None
