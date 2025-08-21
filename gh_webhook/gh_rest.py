"""
GH REST API处理
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from loguru import logger


class LabelColor(Enum):
    """标签颜色"""

    BUG = "d73a4a"  # Bug
    DOC = "0075ca"  # Doc
    FEAT = "a2eeef"  # feat
    GOOD_FIRST_ISSUE = "7057ff"  # good first issue
    HELP_PLUS = "008672"  # help+
    INFORMATION_PLUS = "d876e3"  # information+
    WONT_FIX = "e4e669"  # won't_fix
    NOT_PLANNED = "ffffff"  # 未计划
    NOT_PLANNED_PLUGIN = "5319e7"  # not_planned/plugin
    TODO = "8AF998"  # TODO
    WAITING_VERIFY = "2B99F7"  # 等待验证
    PRIORITY_LOW = "BFF5B2"  # 优先级：低
    PRIORITY_MEDIUM = "ECEE75"  # 优先级：中等
    PRIORITY_HIGH = "ED3A06"  # 优先级：高
    PRIORITY_URGENT = "AC1AEB"  # 优先级：紧急
    BUG_WINDOWS = "0969da"  # bug/Windows
    BUG_LINUX = "FEF2C0"  # bug/Linux
    BUG_MACOS = "CCDDFF"  # bug/macOS
    TEST_REQUIRED_WINDOWS = "367AB4"  # test/required/Windows
    TEST_REQUIRED_MACOS = "367AB4"  # test/required/MacOS
    TEST_REQUIRED_LINUX = "367AB4"  # test/required/Linux
    TEST_FAILED_WINDOWS = "B70205"  # test/failed/Windows
    TEST_FAILED_MACOS = "B70205"  # test/failed/MacOS
    TEST_FAILED_LINUX = "B70205"  # test/failed/Linux
    TEST_ACCEPTED_LINUX = "0E9B16"  # test/accepted/Linux
    TEST_ACCEPTED_MACOS = "0E9B16"  # test/accepted/MacOS
    TEST_ACCEPTED_WINDOWS = "0E9B16"  # test/accepted/Windows
    CIALLO = "0d0721"  # Ciallo~
    WIDGET = "ff6b6b"  # 小组件 - 红色
    PLUGIN = "4ecdc4"  # 插件 - 青色
    SCHEDULE = "45b7d1"  # 课程表 - 蓝色
    CONFIG = "f7b731"  # 配置 - 橙色
    UI = "a55eea"  # UI - 紫色
    NOTIFICATION = "fd79a8"  # 通知提醒 - 粉色
    OTHER = "636e72"  # 其他 - 灰色
    TEST_ACCEPTED_ANY = "0E8A16"  # test/accepted/any
    TEST_FAILED_ANY = "B60205"  # test/failed/any


@dataclass
class GitHubLabel:
    """GitHub标签"""

    name: str
    color: str
    description: Optional[str] = None


@dataclass
class ReviewComment:
    """审查评论"""

    path: str
    line: int
    body: str
    side: str = "RIGHT"  # RIGHT or LEFT


class GitHubAPIClient:
    """GH-API客户端"""

    def __init__(self, token: str, proxy_config: Optional[Dict] = None):
        self.token = token
        self.proxy_config = proxy_config or {}
        self.base_url = "https://api.github.com"
        self.session = None
        # 预定义标签
        self.predefined_labels = {
            "Bug": GitHubLabel("Bug", LabelColor.BUG.value, "Something isn't working"),
            "Doc": GitHubLabel(
                "Doc",
                LabelColor.DOC.value,
                "Improvements or additions to documentation",
            ),
            "feat": GitHubLabel("feat", LabelColor.FEAT.value, "New feature or request"),
            "good first issue": GitHubLabel(
                "good first issue",
                LabelColor.GOOD_FIRST_ISSUE.value,
                "Good for newcomers",
            ),
            "help+": GitHubLabel("help+", LabelColor.HELP_PLUS.value, "需要额外关注"),
            "information+": GitHubLabel(
                "information+",
                LabelColor.INFORMATION_PLUS.value,
                "Further information is requested",
            ),
            "won't_fix": GitHubLabel("won't_fix", LabelColor.WONT_FIX.value, "此问题不适用于本程序"),
            "未计划": GitHubLabel("未计划", LabelColor.NOT_PLANNED.value, "This will not be worked on"),
            "not_planned/plugin": GitHubLabel(
                "not_planned/plugin",
                LabelColor.NOT_PLANNED_PLUGIN.value,
                "可以用插件实现的功能而无需修改程序",
            ),
            "TODO": GitHubLabel("TODO", LabelColor.TODO.value, "正在计划实现的功能"),
            "等待验证": GitHubLabel(
                "等待验证",
                LabelColor.WAITING_VERIFY.value,
                "已尝试修复且开发者已验证，但仍需题主验证是否修复",
            ),
            "优先级：低": GitHubLabel(
                "优先级：低",
                LabelColor.PRIORITY_LOW.value,
                "较低的优先级，处理速度可能会很久",
            ),
            "优先级：中等": GitHubLabel(
                "优先级：中等",
                LabelColor.PRIORITY_MEDIUM.value,
                "中等优先级，在不久的版本会处理",
            ),
            "优先级：高": GitHubLabel(
                "优先级：高",
                LabelColor.PRIORITY_HIGH.value,
                "较高的优先级，可能会在下个版本更新处理",
            ),
            "优先级：紧急": GitHubLabel(
                "优先级：紧急",
                LabelColor.PRIORITY_URGENT.value,
                "紧急修复，处理完成将会直接更新",
            ),
            "bug/Windows": GitHubLabel(
                "bug/Windows",
                LabelColor.BUG_WINDOWS.value,
                "在Windows操作系统会出现的问题",
            ),
            "bug/Linux": GitHubLabel("bug/Linux", LabelColor.BUG_LINUX.value, "在Linux系统会出现的问题"),
            "bug/macOS": GitHubLabel("bug/macOS", LabelColor.BUG_MACOS.value, "在macOS上会出现的问题"),
            "test/required/Windows": GitHubLabel(
                "test/required/Windows",
                LabelColor.TEST_REQUIRED_WINDOWS.value,
                "需要在Windows系统中进行测试",
            ),
            "test/required/MacOS": GitHubLabel(
                "test/required/MacOS",
                LabelColor.TEST_REQUIRED_MACOS.value,
                "需要在MacOS系统中进行测试",
            ),
            "test/required/Linux": GitHubLabel(
                "test/required/Linux",
                LabelColor.TEST_REQUIRED_LINUX.value,
                "需要在Linux系统中进行测试",
            ),
            "test/failed/Windows": GitHubLabel(
                "test/failed/Windows",
                LabelColor.TEST_FAILED_WINDOWS.value,
                "在Windows系统中未通过测试/存在问题",
            ),
            "test/failed/MacOS": GitHubLabel(
                "test/failed/MacOS",
                LabelColor.TEST_FAILED_MACOS.value,
                "在MacOS系统中未通过测试/存在问题",
            ),
            "test/failed/Linux": GitHubLabel(
                "test/failed/Linux",
                LabelColor.TEST_FAILED_LINUX.value,
                "在Linux系统中未通过测试/存在问题",
            ),
            "test/accepted/Linux": GitHubLabel(
                "test/accepted/Linux",
                LabelColor.TEST_ACCEPTED_LINUX.value,
                "在Linux系统中已通过测试",
            ),
            "test/accepted/MacOS": GitHubLabel(
                "test/accepted/MacOS",
                LabelColor.TEST_ACCEPTED_MACOS.value,
                "在MacOS系统中已通过测试",
            ),
            "test/accepted/Windows": GitHubLabel(
                "test/accepted/Windows",
                LabelColor.TEST_ACCEPTED_WINDOWS.value,
                "在Windows系统中已通过测试",
            ),
            "Ciallo~": GitHubLabel("Ciallo~", LabelColor.CIALLO.value, "神秘Tag"),
            "test/accepted/any": GitHubLabel(
                "test/accepted/any",
                LabelColor.TEST_ACCEPTED_ANY.value,
                "在any系统中已通过测试",
            ),
            "test/failed/any": GitHubLabel(
                "test/failed/any",
                LabelColor.TEST_FAILED_ANY.value,
                "在any系统中未通过测试/存在问题",
            ),
            "小组件": GitHubLabel("小组件", LabelColor.WIDGET.value, "与小组件相关的功能或问题"),
            "插件": GitHubLabel("插件", LabelColor.PLUGIN.value, "插件系统相关的功能或问题"),
            "课程表": GitHubLabel("课程表", LabelColor.SCHEDULE.value, "课程表功能相关的问题或改进"),
            "配置": GitHubLabel("配置", LabelColor.CONFIG.value, "配置文件或设置相关的问题"),
            "UI": GitHubLabel("UI", LabelColor.UI.value, "用户界面设计或交互相关的问题"),
            "通知提醒": GitHubLabel("通知提醒", LabelColor.NOTIFICATION.value, "通知和提醒功能相关的问题"),
            "Other": GitHubLabel("Other", LabelColor.OTHER.value, "其他未分类的问题或功能"),
        }
        # 关键字映射
        self.keyword_mappings = {
            "Doc": ["文档", "说明"],
            "小组件": ["小组件", "组件", "控件"],
            "插件": ["插件", "扩展"],
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取HTTP会话"""
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector()
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    "Authorization": f"token {self.token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "GH-API@Baiyao105/1.0 (AnimeBrowser)",
                },
            )
        return self.session

    async def _make_request(self, method: str, url: str, **kwargs) -> Optional[Dict[str, Any]]:
        """发起API请求"""
        session = await self._get_session()
        proxy_url = None
        if self.proxy_config and self.proxy_config.get("enabled"):
            proxy_url = self.proxy_config.get("url")
        try:
            async with session.request(method, url, proxy=proxy_url, **kwargs) as response:
                if response.status == 204:  # No Content
                    return {}

                response_data = await response.json()
                if response.status >= 400:
                    logger.error(f"GH-API请求失败: {response.status}, {response_data}")
                    return None
                return response_data

        except Exception as e:
            logger.error(f"GH-API请求异常: {e}")
            return None

    async def get_repository_labels(self, owner: str, repo: str) -> List[Dict[str, Any]]:
        """获取仓库标签列表"""
        url = f"{self.base_url}/repos/{owner}/{repo}/labels"
        result = await self._make_request("GET", url)
        return result if isinstance(result, list) else []

    async def create_label(self, owner: str, repo: str, label: GitHubLabel) -> bool:
        """创建标签"""
        url = f"{self.base_url}/repos/{owner}/{repo}/labels"
        data = {
            "name": label.name,
            "color": label.color,
            "description": label.description or "",
        }
        result = await self._make_request("POST", url, json=data)
        return result is not None

    async def ensure_labels_exist(self, owner: str, repo: str, labels: List[str]) -> bool:
        """确保标签存在，不存在则创建"""
        try:
            existing_labels = await self.get_repository_labels(owner, repo)
            existing_label_names = {label["name"].lower() for label in existing_labels}
            for label_name in labels:
                if label_name.lower() not in existing_label_names:
                    predefined_label = self.predefined_labels.get(label_name.lower())
                    if predefined_label:
                        success = await self.create_label(owner, repo, predefined_label)
                        if success:
                            logger.success(f"创建标签成功: {label_name}")
                        else:
                            logger.warning(f"创建标签失败: {label_name}")

            return True

        except Exception as e:
            logger.error(f"确保标签存在时异常: {e}")
            return False

    async def add_labels_to_issue(self, owner: str, repo: str, issue_number: int, labels: List[str]) -> bool:
        """为Issue添加标签"""
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}/labels"
        data = {"labels": labels}

        result = await self._make_request("POST", url, json=data)
        return result is not None

    async def remove_labels_from_issue(self, owner: str, repo: str, issue_number: int, labels: List[str]) -> bool:
        """从Issue移除标签"""
        success_count = 0
        for label in labels:
            url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}/labels/{label}"
            result = await self._make_request("DELETE", url)
            if result is not None:
                success_count += 1

        return success_count > 0

    async def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> bool:
        """创建Issue评论"""
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}/comments"
        data = {"body": body}

        result = await self._make_request("POST", url, json=data)
        return result is not None

    async def create_pr_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        event: str = "COMMENT",
        comments: Optional[List[ReviewComment]] = None,
    ) -> bool:
        """创建PR审查"""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"

        data = {"body": body, "event": event}  # APPROVE, REQUEST_CHANGES, COMMENT

        if comments:
            data["comments"] = [
                {
                    "path": comment.path,
                    "line": comment.line,
                    "body": comment.body,
                    "side": comment.side,
                }
                for comment in comments
            ]

        result = await self._make_request("POST", url, json=data)
        return result is not None

    async def get_pr_files(self, owner: str, repo: str, pr_number: int) -> List[Dict[str, Any]]:
        """获取PR文件变更"""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        result = await self._make_request("GET", url)
        return result if isinstance(result, list) else []

    async def get_issue_details(self, owner: str, repo: str, issue_number: int) -> Optional[Dict[str, Any]]:
        """获取Issue详情"""
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}"
        return await self._make_request("GET", url)

    async def get_pr_details(self, owner: str, repo: str, pr_number: int) -> Optional[Dict[str, Any]]:
        """获取PR详情"""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
        return await self._make_request("GET", url)

    async def get_pr_reviews(self, owner: str, repo: str, pr_number: int) -> List[Dict[str, Any]]:
        """获取PR审核列表"""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        result = await self._make_request("GET", url)
        return result if isinstance(result, list) else []

    async def get_pr_review_requests(self, owner: str, repo: str, pr_number: int) -> Dict[str, Any]:
        """获取PR审核请求"""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers"
        result = await self._make_request("GET", url)
        return result if result else {"users": [], "teams": []}

    async def remove_review_request(self, owner: str, repo: str, pr_number: int, reviewers: List[str]) -> bool:
        """移除PR审核请求"""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers"
        data = {"reviewers": reviewers}
        result = await self._make_request("DELETE", url, json=data)
        return result is not None

    async def get_issue_comments(self, owner: str, repo: str, issue_number: int) -> List[Dict[str, Any]]:
        """获取Issue评论列表"""
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}/comments"
        result = await self._make_request("GET", url)
        return result if isinstance(result, list) else []

    async def check_comment_exists(self, owner: str, repo: str, issue_number: int, comment_text: str) -> bool:
        """检查是否存在相同内容的评论"""
        comments = await self.get_issue_comments(owner, repo, issue_number)
        for comment in comments:
            if comment_text.strip() in comment.get("body", "").strip():
                return True
        return False

    async def find_bot_comment_by_keywords(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        keywords: List[str],
        bot_username: str,
    ) -> Optional[Dict[str, Any]]:
        """通过关键字和bot用户名查找评论"""
        comments = await self.get_issue_comments(owner, repo, issue_number)
        for comment in comments:
            comment_body = comment.get("body", "").strip()
            comment_author = comment.get("user", {}).get("login", "")

            # 检查是否是bot发布的评论且包含关键字
            if comment_author == bot_username:
                for keyword in keywords:
                    if keyword.lower() in comment_body.lower():
                        return comment
        return None

    async def update_issue_comment(self, owner: str, repo: str, comment_id: int, body: str) -> bool:
        """更新Issue评论"""
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/comments/{comment_id}"
        data = {"body": body}

        result = await self._make_request("PATCH", url, json=data)
        return result is not None

    async def hide_review_as_outdated(self, owner: str, repo: str, review_id: int) -> bool:
        """将审查标记为过时(隐藏)"""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/reviews/{review_id}/dismissals"
        data = {"message": "重复"}

        result = await self._make_request("PUT", url, json=data)
        return result is not None

    async def close(self):
        """关闭HTTP会话"""
        if self.session and not self.session.closed:
            await self.session.close()


class GitHubEventProcessor:
    """GitHub事件处理器"""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.api_clients = {}  # 缓存不同仓库的API客户端

    def _get_api_client(self, repo_name: str) -> Optional[GitHubAPIClient]:
        """获取仓库的API客户端"""
        if repo_name in self.api_clients:
            return self.api_clients[repo_name]
        repo_config = self.config_manager.get_repository_config(repo_name)
        if not repo_config:
            logger.warning(f"未找到仓库 {repo_name} 的配置")
            return None
        github_config = repo_config.get("github", {})
        token = github_config.get("token") or self.config_manager.get("github", {}).get("token")
        if not token:
            logger.error(f"仓库 {repo_name} 未配置GitHub token")
            return None
        proxy_config = self.config_manager.get("proxy", {})
        client = GitHubAPIClient(token, proxy_config)
        self.api_clients[repo_name] = client

        return client

    def _extract_keywords_from_text(self, text: str, is_issue: bool = True) -> List[str]:
        """从文本中提取关键字

        Args:
            text: 要分析的文本内容
            is_issue: 是否为issue，仅对issue进行标签化处理
        
        Returns:
            匹配到的标签列表
        """
        if not text or not is_issue:
            return []

        text_lower = text.lower().strip()
        detected_labels = []

        if not self.api_clients:
            return []

        first_client = list(self.api_clients.values())[0]
        keyword_mappings = first_client.keyword_mappings
        for label_name, keywords in keyword_mappings.items():
            for keyword in keywords:
                keyword_lower = keyword.lower().strip()
                import re
                pattern = r'\b' + re.escape(keyword_lower) + r'\b'
                if any('\u4e00' <= char <= '\u9fff' for char in keyword_lower):
                    pattern = r'(?<![\w\u4e00-\u9fff])' + re.escape(keyword_lower) + r'(?![\w\u4e00-\u9fff])'

                if re.search(pattern, text_lower):
                    if label_name not in detected_labels:
                        detected_labels.append(label_name)
                    break

        return detected_labels

    def _validate_issue_format(self, issue: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """验证Issue格式"""
        errors = []

        title = issue.get("title", "")
        body = issue.get("body", "")

        # 检查标题长度
        # if len(title) < 10:
        #     errors.append("标题过短，请提供更详细的描述(至少10个字符)")

        # if len(title) > 100:
        #     errors.append("标题过长，请保持在100个字符以内")

        # # 检查是否有描述
        # if not body or len(body.strip()) < 20:
        #     errors.append("请提供详细的问题描述(至少20个字符)")
        # 检查是否包含基本信息(对于bug报告)
        if "bug" in title.lower() or "error" in title.lower():
            required_sections = [
                "重现步骤",
                "期望行为",
                "实际行为",
                "reproduce",
                "expected",
                "actual",
            ]
            has_required_info = any(section.lower() in body.lower() for section in required_sections)
            if not has_required_info:
                errors.append("建议填写信息: 重现步骤、期望行为、实际行为")

        return len(errors) == 0, errors

    def _validate_pr_format(self, pr: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """验证PR格式"""
        errors = []
        pr.get("title", "")
        pr.get("body", "")

        # if len(title) < 10:
        #     errors.append("标题过短，请提供更详细的描述(至少10个字符)")
        # if not body or len(body.strip()) < 30:
        #     errors.append("请提供详细的PR描述(至少30个字符)")
        # change_keywords = ["修改", "添加", "删除", "修复", "add", "remove", "fix", "update", "change"]
        # has_change_info = any(keyword.lower() in body.lower() for keyword in change_keywords)
        # if not has_change_info:
        #     errors.append("请在描述中说明具体的变更内容")
        head_ref = pr.get("head", {}).get("ref", "")
        if head_ref in ["main", "master", "develop"]:
            errors.append("建议: 请不要直接从主分支创建PR")

        return len(errors) == 0, errors

    async def process_issue_event(self, payload: Dict[str, Any]) -> bool:
        """处理Issue事件"""
        try:
            action = payload.get("action", "")
            issue = payload.get("issue", {})
            repository = payload.get("repository", {})
            repo_name = repository.get("full_name", "")
            issue_number = issue.get("number", 0)
            if not repo_name or not issue_number:
                logger.warning("Issue事件缺少必要信息")
                return False

            client = self._get_api_client(repo_name)
            if not client:
                return False
            owner, repo = repo_name.split("/")
            if action == "opened":
                await self._handle_issue_opened(client, owner, repo, issue)
            elif action == "edited":
                await self._handle_issue_edited(client, owner, repo, issue)
            return True

        except Exception as e:
            logger.error(f"处理Issue事件异常: {e}")
            return False

    async def _handle_issue_opened(self, client: GitHubAPIClient, owner: str, repo: str, issue: Dict[str, Any]):
        """处理Issue创建事件"""
        issue_number = issue.get("number", 0)
        title = issue.get("title", "")
        body = issue.get("body", "")
        is_valid, format_errors = self._validate_issue_format(issue)

        if not is_valid:
            error_message = "## Issue格式问题\n\n" + "\n".join(f"- {error}" for error in format_errors)
            error_message += "\n\n建议修改Issue内容以符合规范(当然可以忽略("
            await client.create_issue_comment(owner, repo, issue_number, error_message)
            logger.info(f"发送Issue格式提醒: {owner}/{repo}#{issue_number}")

        detected_labels = self._extract_keywords_from_text(f"{title} {body}", is_issue=True)

        if detected_labels:
            await client.ensure_labels_exist(owner, repo, detected_labels)
            success = await client.add_labels_to_issue(owner, repo, issue_number, detected_labels)
            if success:
                logger.success(f"自动添加Issue标签成功: {owner}/{repo}#{issue_number} -> {detected_labels}")
            else:
                logger.warning(f"自动添加Issue标签失败: {owner}/{repo}#{issue_number}")

    async def _handle_issue_edited(self, client: GitHubAPIClient, owner: str, repo: str, issue: Dict[str, Any]):
        """处理Issue编辑事件"""
        # TODO: 不知道

    async def process_pr_event(self, payload: Dict[str, Any]) -> bool:
        """处理PR事件"""
        try:
            action = payload.get("action", "")
            pr = payload.get("pull_request", {})
            repository = payload.get("repository", {})
            repo_name = repository.get("full_name", "")
            pr_number = pr.get("number", 0)
            if not repo_name or not pr_number:
                logger.warning("PR事件缺少必要信息")
                return False
            client = self._get_api_client(repo_name)
            if not client:
                return False
            owner, repo = repo_name.split("/")
            if action == "opened":
                await self._handle_pr_opened(client, owner, repo, pr)
            elif action == "synchronize":  # PR更新
                await self._handle_pr_updated(client, owner, repo, pr)
            return True

        except Exception as e:
            logger.error(f"处理PR事件异常: {e}")
            return False

    async def _handle_pr_opened(self, client: GitHubAPIClient, owner: str, repo: str, pr: Dict[str, Any]):
        """处理PR创建事件"""
        pr_number = pr.get("number", 0)
        title = pr.get("title", "")
        body = pr.get("body", "")
        is_valid, format_errors = self._validate_pr_format(pr)

        if not is_valid:
            error_message = "## PR格式问题\n\n" + "\n".join(f"- {error}" for error in format_errors)
            error_message += "\n\n建议修改PR内容以符合规范(当然可以忽略("
            await client.create_issue_comment(owner, repo, pr_number, error_message)
            logger.info(f"发送PR格式提醒: {owner}/{repo}#{pr_number}")
        # logger.info(f"PR创建事件处理完成, 跳过标签化处理: {owner}/{repo}#{pr_number}")

    async def _handle_pr_updated(self, client: GitHubAPIClient, owner: str, repo: str, pr: Dict[str, Any]):
        """处理PR更新事件"""
        # TODO: 不知道

    def _analyze_file_changes(self, files: List[Dict[str, Any]]) -> List[str]:
        """分析文件变更并返回相应标签"""
        labels = []

        for file_info in files:
            filename = file_info.get("filename", "")
            if any(filename.lower().endswith(ext) for ext in [".md", ".rst", ".txt", ".doc"]):
                if "documentation" not in labels:
                    labels.append("documentation")
            if "test" in filename.lower() or filename.lower().startswith("test_"):
                if "tests" not in labels:
                    labels.append("tests")
            if any(filename.lower().endswith(ext) for ext in [".json", ".yaml", ".yml", ".toml", ".ini"]):
                if "configuration" not in labels:
                    labels.append("configuration")

        return labels

    async def submit_ai_review(self, repo_name: str, pr_number: int, review_result) -> bool:
        """提交审查结果"""
        try:
            client = self._get_api_client(repo_name)
            if not client:
                return False
            owner, repo = repo_name.split("/")
            review_body = self._format_ai_review_comment(review_result)
            approved = review_result.get("approved", True) if isinstance(review_result, dict) else getattr(review_result, "approved", True)
            score = review_result.get("overall_score", 85) if isinstance(review_result, dict) else getattr(review_result, "overall_score", 85)
            if approved and score >= 90:  # APPROVE的门槛
                event = "APPROVE"
            else:
                event = "COMMENT"  # 其他情况都使用COMMENT
            # 行级评论
            line_comments = self._create_line_comments(review_result)
            success = await client.create_pr_review(owner, repo, pr_number, review_body, event, line_comments)
            if success:
                logger.info(f"AI审查结果提交成功: {owner}/{repo}#{pr_number}")
            else:
                logger.error(f"AI审查结果提交失败: {owner}/{repo}#{pr_number}")

            return success

        except Exception as e:
            logger.error(f"提交AI审查结果异常: {e}")
            return False

    def _format_ai_review_comment(self, review_result) -> str:
        """格式化AI审查评论"""
        if isinstance(review_result, dict):
            score = review_result.get("overall_score", 85)
            summary = review_result.get("summary", review_result.get("review_content", "AI审查完成"))
            approved = review_result.get("approved", True)
            issues_count = review_result.get("issues_count", {})
        else:
            score = getattr(review_result, "overall_score", 85)
            summary = getattr(review_result, "summary", getattr(review_result, "review_content", "AI审查完成"))
            approved = getattr(review_result, "approved", True)
            issues_count = getattr(review_result, "issues_count", {})

        # 评分表情
        if score >= 90:
            score_emoji = "🎉"
        elif score >= 80:
            score_emoji = "✅"
        elif score >= 70:
            score_emoji = "⚠️"
        elif score >= 60:
            score_emoji = "❌"
        else:
            score_emoji = "🚨"

        comment_lines = [
            f"## {score_emoji} AI代码审查报告",
            "",
            f"**总体评分**: {score:.1f}/100",
            f"**审查状态**: {'✅ 通过' if approved else '❌ 需要改进'}",
            "",
            f"**总结**: {summary}",
        ]

        # 问题统计
        if any(count > 0 for count in issues_count.values()):
            comment_lines.extend(["", "### 📊 问题统计", ""])

            for severity, count in issues_count.items():
                if count > 0:
                    severity_emoji = {
                        "critical": "🚨",
                        "high": "❌",
                        "error": "❌",
                        "medium": "⚠️",
                        "warning": "⚠️",
                        "low": "ℹ️",
                        "info": "ℹ️",
                    }.get(severity, "ℹ️")
                    comment_lines.append(f"- {severity_emoji} {severity.title()}: {count}")

        comment_lines.extend(["", "---", "✨ Powered by **baiyao105**' GitHub Bot"])

        return "\n".join(comment_lines)

    def _create_line_comments(self, review_result) -> List[ReviewComment]:
        """创建行级评论"""
        line_comments = []

        comments = review_result.comments
        for comment in comments[:10]:  # 限制评论数量
            try:
                line_comment = ReviewComment(
                    path=comment.file_path,
                    line=comment.line_number,
                    body=f"**{comment.severity.value.title()}**: {comment.message}\n\n{comment.suggestion or ''}",
                )
                line_comments.append(line_comment)
            except Exception as e:
                logger.warning(f"创建行级评论失败: {e}")

        return line_comments

    async def cleanup(self):
        """清理资源"""
        for client in self.api_clients.values():
            await client.close()
        self.api_clients.clear()


# 全局GitHub事件处理器实例
_github_processor = None


def get_github_processor(config_manager) -> GitHubEventProcessor:
    """获取全局GitHub事件处理器实例"""
    global _github_processor
    if _github_processor is None:
        _github_processor = GitHubEventProcessor(config_manager)
    return _github_processor


async def cleanup_github_processor():
    """清理GitHub事件处理器资源"""
    global _github_processor
    if _github_processor:
        await _github_processor.cleanup()
        _github_processor = None
