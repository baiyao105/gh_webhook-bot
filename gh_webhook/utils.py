"""
验证器
"""

import hashlib
import hmac
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from loguru import logger


def verify_github_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
    """
    验证GitHub webhook签名

    Args:
        payload_body: 请求体字节数据
        signature_header: GitHub签名头 (X-Hub-Signature 或 X-Hub-Signature-256)
        secret: webhook密钥

    Returns:
        bool: 签名是否有效
    """
    if not signature_header or not secret:
        logger.debug("签名头或密钥为空")
        return True

    try:
        if signature_header.startswith("sha1="):
            hash_algorithm = hashlib.sha1
            signature = signature_header[5:]
            logger.debug("使用SHA1签名验证")
        elif signature_header.startswith("sha256="):
            hash_algorithm = hashlib.sha256
            signature = signature_header[7:]
            logger.debug("使用SHA256签名验证")
        else:
            logger.warning(f"不支持的签名算法: {signature_header[:20]}...")
            return False

        expected_signature = hmac.new(secret.encode("utf-8"), payload_body, hash_algorithm).hexdigest()
        is_valid = hmac.compare_digest(signature, expected_signature)
        if not is_valid:
            logger.warning("签名验证失败")
        # else:
        #     logger.success("签名验证成功")
        return is_valid

    except Exception as e:
        logger.error(f"签名验证过程中发生异常: {e}")
        return False


def is_valid_url(url: str) -> bool:
    """
    验证URL是否有效

    Args:
        url: 要验证的URL

    Returns:
        bool: URL是否有效
    """
    if not url or not isinstance(url, str):
        return False

    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc]) and result.scheme in [
            "http",
            "https",
        ]
    except Exception:
        return False


def extract_repo_name(payload: Dict[str, Any]) -> Optional[str]:
    """
    从webhook payload中提取仓库名称

    Args:
        payload: webhook payload数据

    Returns:
        str: 仓库名称 (格式: owner/repo) 或 None
    """
    try:
        return payload.get("repository", {}).get("full_name")
    except Exception as e:
        logger.error(f"提取仓库名称失败: {e}")
        return None


def extract_user_from_at(message: str) -> Optional[str]:
    """
    从消息中提取@用户的QQ号

    Args:
        message: 包含@用户的消息

    Returns:
        str: QQ号或None
    """
    try:
        at_match = re.search(r"\[CQ:at,qq=(\d+)\]", message)
        if at_match:
            return at_match.group(1)
        return None
    except Exception as e:
        logger.error(f"提取@用户失败: {e}")
        return None


def format_uptime(seconds: float) -> str:
    """
    格式化运行时间

    Args:
        seconds: 运行秒数

    Returns:
        str: 格式化的时间字符串
    """
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}分钟"
    elif seconds < 86400:
        return f"{seconds / 3600:.1f}小时"
    else:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        return f"{days}天{hours}小时"


def format_file_size(size_bytes: int) -> str:
    """
    格式化文件大小

    Args:
        size_bytes: 字节数

    Returns:
        str: 格式化的大小字符串
    """
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"


def sanitize_filename(filename: str) -> str:
    """
    清理文件名, 移除不安全字符

    Args:
        filename: 原始文件名

    Returns:
        str: 清理后的文件名
    """
    # 移除或替换不安全字符
    unsafe_chars = r'[<>:"/\\|?*]'
    safe_filename = re.sub(unsafe_chars, "_", filename)
    safe_filename = safe_filename.strip(". ")
    if not safe_filename:
        safe_filename = "unnamed"
    if len(safe_filename) > 200:
        safe_filename = safe_filename[:200]

    return safe_filename


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    截断文本到指定长度

    Args:
        text: 原始文本
        max_length: 最大长度
        suffix: 截断后缀

    Returns:
        str: 截断后的文本
    """
    if not text or len(text) <= max_length:
        return text

    return text[: max_length - len(suffix)] + suffix


def is_github_event_valid(event_type: str) -> bool:
    """
    验证GitHub事件类型是否有效

    Args:
        event_type: 事件类型

    Returns:
        bool: 是否为有效的GitHub事件类型
    """
    valid_events = {
        "push",
        "issues",
        "pull_request",
        "release",
        "fork",
        "star",
        "watch",
        "create",
        "delete",
        "commit_comment",
        "issue_comment",
        "pull_request_review",
        "pull_request_review_comment",
        "gollum",
        "deployment",
        "deployment_status",
        "dependabot_alert",
        "workflow_job",
        "workflow_run",
        "check_run",
        "check_suite",
        "status",
        "ping",
    }
    return event_type in valid_events


def extract_pr_number(text: str) -> Optional[int]:
    """
    从文本中提取PR编号

    Args:
        text: 包含PR编号的文本

    Returns:
        int: PR编号或None
    """
    try:
        # 匹配 #123 或 PR #123 或 pull request #123
        patterns = [r"#(\d+)", r"PR\s*#(\d+)", r"pull\s+request\s*#(\d+)"]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None
    except Exception as e:
        logger.error(f"提取PR编号失败: {e}")
        return None


def extract_issue_number(text: str) -> Optional[int]:
    """
    从文本中提取Issue编号

    Args:
        text: 包含Issue编号的文本

    Returns:
        int: Issue编号或None
    """
    try:
        # 匹配 #123 或 issue #123
        patterns = [r"#(\d+)", r"issue\s*#(\d+)"]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None
    except Exception as e:
        logger.error(f"提取Issue编号失败: {e}")
        return None


def get_current_timestamp() -> float:
    """
    获取当前时间戳

    Returns:
        float: 当前时间戳
    """
    return time.time()


def is_rate_limited(ip: str, rate_limits: Dict[str, Dict], limit: int = 100, window: int = 3600) -> bool:
    """
    检查IP是否被限流

    Args:
        ip: IP地址
        rate_limits: 限流记录字典
        limit: 限制次数
        window: 时间窗口(秒)

    Returns:
        bool: 是否被限流
    """
    current_time = get_current_timestamp()

    if ip not in rate_limits:
        rate_limits[ip] = {"count": 1, "window_start": current_time}
        return False

    ip_data = rate_limits[ip]
    if current_time - ip_data["window_start"] > window:
        ip_data["count"] = 1
        ip_data["window_start"] = current_time
        return False
    # 在同一时间窗口内, 增加计数
    ip_data["count"] += 1

    return ip_data["count"] > limit


def clean_rate_limits(rate_limits: Dict[str, Dict], window: int = 3600) -> int:
    """
    清理过期的限流记录

    Args:
        rate_limits: 限流记录字典
        window: 时间窗口(秒)

    Returns:
        int: 清理的记录数
    """
    current_time = get_current_timestamp()
    expired_ips = []

    for ip, data in rate_limits.items():
        if current_time - data["window_start"] > window:
            expired_ips.append(ip)

    for ip in expired_ips:
        rate_limits.pop(ip, None)

    return len(expired_ips)


def validate_webhook_payload(payload: Dict[str, Any], event_type: str) -> bool:
    """
    验证webhook payload的基本结构

    Args:
        payload: webhook payload
        event_type: 事件类型

    Returns:
        bool: payload是否有效
    """
    try:
        if not isinstance(payload, dict):
            return False
        if event_type != "ping" and "repository" not in payload:
            return False
        # 检查repository结构
        if event_type != "ping":
            repo = payload.get("repository", {})
            if not isinstance(repo, dict) or "full_name" not in repo:
                return False
        return True
    except Exception as e:
        logger.error(f"验证webhook payload失败: {e}")
        return False


class RateLimiter:
    """
    暴力内存限流器
    """

    def __init__(self, limit: int = 100, window: int = 3600):
        self.limit = limit
        self.window = window
        self.records = {}

    def is_allowed(self, key: str) -> bool:
        """
        检查是否允许请求

        Args:
            key: 限流键

        Returns:
            bool: 是否允许
        """
        return not is_rate_limited(key, self.records, self.limit, self.window)

    def cleanup(self) -> int:
        """
        清理过期记录

        Returns:
            int: 清理的记录数
        """
        return clean_rate_limits(self.records, self.window)


# 全局工具实例
_utils_instance = None


def get_utils_instance():
    """
    获取工具实例

    Returns:
        dict: 包含所有工具函数的字典
    """
    global _utils_instance
    if _utils_instance is None:
        _utils_instance = {
            "verify_github_signature": verify_github_signature,
            "is_valid_url": is_valid_url,
            "extract_repo_name": extract_repo_name,
            "extract_user_from_at": extract_user_from_at,
            "format_uptime": format_uptime,
            "format_file_size": format_file_size,
            "sanitize_filename": sanitize_filename,
            "truncate_text": truncate_text,
            "is_github_event_valid": is_github_event_valid,
            "extract_pr_number": extract_pr_number,
            "extract_issue_number": extract_issue_number,
            "get_current_timestamp": get_current_timestamp,
            "is_rate_limited": is_rate_limited,
            "clean_rate_limits": clean_rate_limits,
            "validate_webhook_payload": validate_webhook_payload,
            "RateLimiter": RateLimiter,
        }
        # logger.debug("工具实例初始化成功")
    return _utils_instance


def cleanup_utils():
    """
    清理工具实例
    """
    global _utils_instance
    if _utils_instance is not None:
        logger.debug("清理工具实例")
        _utils_instance = None
