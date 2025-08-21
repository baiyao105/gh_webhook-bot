# -*- coding: utf-8 -*-
"""
AI代码审查引擎
提供标准化的AI审查逻辑、返回格式和提示词管理
"""

import asyncio
import json
import re
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Union, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum

from loguru import logger


class ReviewSeverity(Enum):
    """审查问题严重程度"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ReviewStatus(Enum):
    """审查状态"""
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    COMMENTED = "commented"
    FAILED = "failed"


@dataclass
class ReviewComment:
    """审查评论数据结构"""
    file_path: str
    line_number: int
    severity: ReviewSeverity
    message: str
    suggestion: Optional[str] = None
    category: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "file_path": self.file_path,
            "line_number": self.line_number,
            "severity": self.severity.value,
            "message": self.message,
            "suggestion": self.suggestion,
            "category": self.category
        }


@dataclass
class ReviewResult:
    """标准化审查结果数据结构"""
    success: bool
    repository: str
    pr_number: int
    overall_score: float
    approved: bool
    status: ReviewStatus
    summary: str
    detailed_analysis: str
    comments: List[ReviewComment]
    issues_count: Dict[str, int]
    review_time: datetime
    context_id: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，保持向后兼容"""
        return {
            "success": self.success,
            "repository": self.repository,
            "pr_number": self.pr_number,
            "overall_score": self.overall_score,
            "approved": self.approved,
            "status": self.status.value,
            "summary": self.summary,
            "detailed_analysis": self.detailed_analysis,
            "comments": [comment.to_dict() for comment in self.comments],
            "issues_count": self.issues_count,
            "review_time": self.review_time.isoformat(),
            "context_id": self.context_id,
            "error": self.error,
            # 向后兼容字段
            "review_content": self.detailed_analysis
        }


class AIReviewPromptManager:
    """AI审查提示词管理器"""
    
    @staticmethod
    def get_code_review_prompt(repo_name: str, pr_number: int, pr_title: str, 
                              pr_body: str, pr_files: List[Dict[str, Any]]) -> str:
        """生成标准化的代码审查提示词"""
        
        # 构建文件变更信息
        files_info = []
        for file_info in pr_files[:10]:  # 限制文件数量避免提示词过长
            file_path = file_info.get('filename', '')
            status = file_info.get('status', '')
            additions = file_info.get('additions', 0)
            deletions = file_info.get('deletions', 0)
            patch = file_info.get('patch', '')[:2000]  # 限制patch长度
            
            files_info.append(f"""
### 文件: {file_path}
- 状态: {status}
- 新增行数: {additions}
- 删除行数: {deletions}
- 变更内容:
```diff
{patch}
```
""")
        
        files_content = "\n".join(files_info)
        
        return f"""
# AI代码审查任务

## 基本信息
- **仓库**: {repo_name}
- **PR编号**: #{pr_number}
- **标题**: {pr_title}
- **描述**: {pr_body or "无描述"}

## 文件变更
{files_content}

## 审查要求

请对以上Pull Request进行全面的代码审查，并严格按照以下JSON格式返回结果：

```json
{{
  "overall_score": 85.5,
  "approved": true,
  "status": "approved",
  "summary": "整体代码质量良好，建议合并",
  "detailed_analysis": "详细的审查分析...",
  "comments": [
    {{
      "file_path": "src/example.py",
      "line_number": 42,
      "severity": "warning",
      "message": "建议使用更具描述性的变量名",
      "suggestion": "将变量名从'x'改为'user_count'",
      "category": "code_quality"
    }}
  ],
  "issues_count": {{
    "critical": 0,
    "error": 0,
    "warning": 2,
    "info": 1
  }}
}}
```

## 审查重点

1. **代码质量**: 检查代码风格、命名规范、注释质量
2. **安全性**: 识别潜在的安全漏洞和风险
3. **性能**: 评估代码性能和优化建议
4. **可维护性**: 代码结构、模块化程度、可读性
5. **最佳实践**: 是否遵循语言和框架的最佳实践
6. **测试覆盖**: 是否需要添加或修改测试

## 评分标准

- **90-100分**: 优秀，代码质量很高，可以直接合并
- **80-89分**: 良好，有少量改进建议但不影响合并
- **70-79分**: 一般，需要一些改进但整体可接受
- **60-69分**: 较差，存在明显问题需要修改
- **60分以下**: 不合格，存在严重问题必须修改

## 输出要求

1. **必须返回有效的JSON格式**
2. **overall_score**: 0-100的数值评分
3. **approved**: 是否建议合并 (true/false)
4. **status**: 审查状态 ("approved", "changes_requested", "commented")
5. **summary**: 简洁的总结 (50-200字)
6. **detailed_analysis**: 详细分析 (200-1000字)
7. **comments**: 具体的代码评论数组
8. **issues_count**: 按严重程度统计的问题数量

请确保返回的JSON格式正确，可以被程序解析。
"""


class AIReviewResultParser:
    """AI审查结果解析器"""
    
    @staticmethod
    def parse_ai_response(ai_response: str, repo_name: str, pr_number: int, 
                         context_id: Optional[str] = None) -> ReviewResult:
        """解析AI响应为标准化结果"""
        try:
            # 尝试从响应中提取JSON
            json_match = re.search(r'```json\s*({.*?})\s*```', ai_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 尝试直接解析整个响应
                json_str = ai_response.strip()
            
            # 解析JSON
            try:
                parsed_data = json.loads(json_str)
            except json.JSONDecodeError:
                # JSON解析失败，创建基于文本的结果
                return AIReviewResultParser._create_fallback_result(
                    ai_response, repo_name, pr_number, context_id
                )
            
            # 验证和标准化数据
            return AIReviewResultParser._create_standardized_result(
                parsed_data, ai_response, repo_name, pr_number, context_id
            )
            
        except Exception as e:
            logger.error(f"解析AI审查结果异常: {e}")
            return AIReviewResultParser._create_error_result(
                str(e), repo_name, pr_number, context_id
            )
    
    @staticmethod
    def _create_standardized_result(parsed_data: Dict[str, Any], original_response: str,
                                  repo_name: str, pr_number: int, 
                                  context_id: Optional[str]) -> ReviewResult:
        """创建标准化结果"""
        # 解析评论
        comments = []
        for comment_data in parsed_data.get("comments", []):
            try:
                comment = ReviewComment(
                    file_path=comment_data.get("file_path", ""),
                    line_number=int(comment_data.get("line_number", 0)),
                    severity=ReviewSeverity(comment_data.get("severity", "info")),
                    message=comment_data.get("message", ""),
                    suggestion=comment_data.get("suggestion"),
                    category=comment_data.get("category")
                )
                comments.append(comment)
            except (ValueError, TypeError) as e:
                logger.warning(f"解析评论失败: {e}, 数据: {comment_data}")
                continue
        
        # 获取评分和状态
        overall_score = float(parsed_data.get("overall_score", 85.0))
        approved = bool(parsed_data.get("approved", overall_score >= 80))
        
        # 确定状态
        status_str = parsed_data.get("status", "")
        if status_str in ["approved", "changes_requested", "commented"]:
            status = ReviewStatus(status_str)
        else:
            # 根据评分和批准状态推断
            if approved and overall_score >= 90:
                status = ReviewStatus.APPROVED
            elif overall_score < 70:
                status = ReviewStatus.CHANGES_REQUESTED
            else:
                status = ReviewStatus.COMMENTED
        
        # 问题统计
        issues_count = parsed_data.get("issues_count", {})
        if not issues_count:
            # 从评论中统计
            issues_count = {"critical": 0, "error": 0, "warning": 0, "info": 0}
            for comment in comments:
                severity_key = comment.severity.value
                if severity_key in issues_count:
                    issues_count[severity_key] += 1
        
        return ReviewResult(
            success=True,
            repository=repo_name,
            pr_number=pr_number,
            overall_score=overall_score,
            approved=approved,
            status=status,
            summary=parsed_data.get("summary", "AI审查完成"),
            detailed_analysis=parsed_data.get("detailed_analysis", original_response),
            comments=comments,
            issues_count=issues_count,
            review_time=datetime.now(),
            context_id=context_id
        )
    
    @staticmethod
    def _create_fallback_result(ai_response: str, repo_name: str, pr_number: int,
                              context_id: Optional[str]) -> ReviewResult:
        """创建基于文本的备用结果"""
        # 简单的文本分析来推断评分
        response_lower = ai_response.lower()
        
        # 推断评分
        if any(word in response_lower for word in ["优秀", "excellent", "perfect", "很好"]):
            score = 90.0
        elif any(word in response_lower for word in ["良好", "good", "不错"]):
            score = 80.0
        elif any(word in response_lower for word in ["问题", "错误", "bug", "issue"]):
            score = 65.0
        else:
            score = 75.0
        
        approved = score >= 80
        status = ReviewStatus.APPROVED if approved else ReviewStatus.COMMENTED
        
        return ReviewResult(
            success=True,
            repository=repo_name,
            pr_number=pr_number,
            overall_score=score,
            approved=approved,
            status=status,
            summary="AI审查完成（文本解析）",
            detailed_analysis=ai_response,
            comments=[],
            issues_count={"critical": 0, "error": 0, "warning": 0, "info": 0},
            review_time=datetime.now(),
            context_id=context_id
        )
    
    @staticmethod
    def _create_error_result(error_msg: str, repo_name: str, pr_number: int,
                           context_id: Optional[str]) -> ReviewResult:
        """创建错误结果"""
        return ReviewResult(
            success=False,
            repository=repo_name,
            pr_number=pr_number,
            overall_score=0.0,
            approved=False,
            status=ReviewStatus.FAILED,
            summary=f"审查异常: {error_msg}",
            detailed_analysis=f"审查过程中发生异常: {error_msg}",
            comments=[],
            issues_count={"critical": 1},
            review_time=datetime.now(),
            context_id=context_id,
            error=error_msg
        )


class AIReviewValidator:
    """AI审查结果验证器"""
    
    @staticmethod
    def validate_review_result(result: ReviewResult) -> Tuple[bool, List[str]]:
        """验证审查结果的完整性和正确性"""
        errors = []
        
        # 基本字段验证
        if not result.repository:
            errors.append("仓库名称不能为空")
        
        if result.pr_number <= 0:
            errors.append("PR编号必须大于0")
        
        if not (0 <= result.overall_score <= 100):
            errors.append("评分必须在0-100之间")
        
        if not result.summary:
            errors.append("审查总结不能为空")
        
        # 逻辑一致性验证
        if result.approved and result.overall_score < 70:
            errors.append("评分过低但标记为批准，逻辑不一致")
        
        if result.status == ReviewStatus.APPROVED and not result.approved:
            errors.append("状态为批准但approved字段为False")
        
        # 评论验证
        for i, comment in enumerate(result.comments):
            if not comment.file_path:
                errors.append(f"评论{i+1}缺少文件路径")
            
            if comment.line_number <= 0:
                errors.append(f"评论{i+1}行号无效")
            
            if not comment.message:
                errors.append(f"评论{i+1}缺少消息内容")
        
        # 问题统计验证
        expected_keys = {"critical", "error", "warning", "info"}
        if not expected_keys.issubset(result.issues_count.keys()):
            errors.append("问题统计缺少必要的严重程度分类")
        
        return len(errors) == 0, errors


class EnhancedAIReviewEngine:
    """增强的AI审查引擎"""
    
    def __init__(self, ai_handler):
        self.ai_handler = ai_handler
        self.prompt_manager = AIReviewPromptManager()
        self.result_parser = AIReviewResultParser()
        self.validator = AIReviewValidator()
    
    async def review_code_changes(self, pull_request: Dict[str, Any], 
                                repository: Dict[str, Any],
                                pr_files: Optional[List[Dict[str, Any]]] = None) -> ReviewResult:
        """执行标准化的代码审查"""
        repo_name = repository.get("full_name", "")
        pr_number = pull_request.get("number", 0)
        pr_title = pull_request.get("title", "")
        pr_body = pull_request.get("body", "")
        
        logger.info(f"开始标准化代码审查: {repo_name}#{pr_number}")
        
        # 输入验证
        if not repo_name:
            logger.error("仓库名称不能为空")
            return self.result_parser._create_error_result(
                "仓库名称不能为空", repo_name or "unknown", pr_number, None
            )
        
        if pr_number <= 0:
            logger.error(f"无效的PR编号: {pr_number}")
            return self.result_parser._create_error_result(
                f"无效的PR编号: {pr_number}", repo_name, pr_number, None
            )
        
        context_id = None
        
        try:
            # 生成上下文ID
            try:
                from .ai_models import ContextType
                context_id = self.ai_handler._generate_context_id(
                    ContextType.GITHUB_PR_REVIEW,
                    repository=repo_name,
                    pr_number=pr_number
                )
            except Exception as e:
                logger.warning(f"生成上下文ID失败: {e}，使用默认值")
                context_id = f"pr_review_{repo_name}_{pr_number}"
            
            # 获取或创建上下文
            context = None
            try:
                context = self.ai_handler.context_manager.get_or_create_context(
                    context_id,
                    ContextType.GITHUB_PR_REVIEW,
                    metadata={
                        "repository": repo_name,
                        "pr_number": pr_number,
                        "pr_title": pr_title
                    }
                )
            except Exception as e:
                logger.warning(f"创建上下文失败: {e}，将使用简化模式")
            
            # 如果没有提供文件信息，尝试获取
            if not pr_files:
                try:
                    pr_files = await self._get_pr_files(repo_name, pr_number)
                except Exception as e:
                    logger.warning(f"获取PR文件信息失败: {e}，将使用空文件列表")
                    pr_files = []
            
            # 生成标准化提示词
            try:
                review_prompt = self.prompt_manager.get_code_review_prompt(
                    repo_name, pr_number, pr_title, pr_body, pr_files or []
                )
            except Exception as e:
                logger.error(f"生成审查提示词失败: {e}")
                return self.result_parser._create_error_result(
                    f"生成审查提示词失败: {str(e)}", repo_name, pr_number, context_id
                )
            
            # 调用AI进行审查（带重试机制）
            ai_response = None
            max_retries = 3
            
            for attempt in range(max_retries):
                try:
                    ai_response = await asyncio.wait_for(
                        self.ai_handler._generate_ai_response(
                            context=context,
                            current_message=review_prompt,
                            user_id="ai_reviewer",
                            github_username="ChimeYao-bot",
                            user_permissions=["ai_review"]
                        ),
                        timeout=180  # 3分钟超时
                    )
                    if ai_response and ai_response.strip():
                        break
                    else:
                        logger.warning(f"AI返回空响应 - 尝试 {attempt + 1}/{max_retries}")
                        
                except asyncio.TimeoutError:
                    logger.warning(f"AI审查超时 - 尝试 {attempt + 1}/{max_retries}: {repo_name}#{pr_number}")
                    if attempt == max_retries - 1:
                        return self.result_parser._create_error_result(
                            "AI审查服务响应超时，请稍后重试", repo_name, pr_number, context_id
                        )
                    await asyncio.sleep(2 ** attempt)  # 指数退避
                    
                except Exception as e:
                    logger.error(f"AI审查请求失败 - 尝试 {attempt + 1}/{max_retries}: {e}")
                    if attempt == max_retries - 1:
                        return self.result_parser._create_error_result(
                            f"AI服务调用失败: {str(e)}", repo_name, pr_number, context_id
                        )
                    await asyncio.sleep(1)
            
            if not ai_response or not ai_response.strip():
                logger.error(f"AI审查未生成有效响应: {repo_name}#{pr_number}")
                return self.result_parser._create_error_result(
                    "AI服务未返回有效响应，请检查服务状态", repo_name, pr_number, context_id
                )
            
            # 解析AI响应
            try:
                result = self.result_parser.parse_ai_response(
                    ai_response, repo_name, pr_number, context_id
                )
            except Exception as e:
                logger.error(f"解析AI响应失败: {e}")
                return self.result_parser._create_error_result(
                    f"响应解析失败: {str(e)}", repo_name, pr_number, context_id
                )
            
            # 验证结果
            try:
                is_valid, validation_errors = self.validator.validate_review_result(result)
                if not is_valid:
                    logger.warning(f"审查结果验证失败: {validation_errors}")
                    # 尝试修复常见问题
                    result = self._fix_validation_issues(result, validation_errors)
            except Exception as e:
                logger.error(f"验证审查结果时发生错误: {e}")
                # 验证失败不阻止返回结果，但记录错误
            
            logger.success(f"标准化代码审查完成: {repo_name}#{pr_number}, 评分: {result.overall_score}")
            return result
            
        except Exception as e:
            logger.error(f"标准化代码审查发生未预期异常: {e}")
            return self.result_parser._create_error_result(
                f"审查过程中发生未预期错误: {str(e)}", repo_name, pr_number, context_id
            )
    
    def _fix_validation_issues(self, result: ReviewResult, validation_errors: List[str]) -> ReviewResult:
        """尝试修复验证问题"""
        try:
            # 修复评分范围问题
            if result.overall_score < 0:
                result.overall_score = 0.0
            elif result.overall_score > 100:
                result.overall_score = 100.0
            
            # 修复逻辑一致性问题
            if result.approved and result.overall_score < 70:
                result.approved = False
                result.status = ReviewStatus.CHANGES_REQUESTED
            
            # 确保问题统计包含所有必要字段
            required_keys = {"critical", "error", "warning", "info"}
            for key in required_keys:
                if key not in result.issues_count:
                    result.issues_count[key] = 0
            
            # 修复空字段
            if not result.summary:
                result.summary = "AI审查完成"
            
            if not result.detailed_analysis:
                result.detailed_analysis = "详细分析信息不可用"
            
            logger.info(f"已修复 {len(validation_errors)} 个验证问题")
            
        except Exception as e:
            logger.error(f"修复验证问题时发生错误: {e}")
        
        return result
    
    async def _get_pr_files(self, repo_name: str, pr_number: int) -> List[Dict[str, Any]]:
        """获取PR文件变更信息"""
        try:
            # 通过MCP工具获取PR文件信息
            if hasattr(self.ai_handler, 'mcp_tools') and self.ai_handler.mcp_tools:
                owner, repo = repo_name.split("/")
                result = await self.ai_handler._call_mcp_tool(
                    "get_pull_request",
                    {"owner": owner, "repo": repo, "pr_number": pr_number}
                )
                
                if result.get("success") and "files" in result.get("data", {}):
                    return result["data"]["files"]
            
            return []
        except Exception as e:
            logger.warning(f"获取PR文件信息失败: {e}")
            return []