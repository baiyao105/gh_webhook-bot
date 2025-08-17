"""
提示词引擎on jinja2
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, Template, TemplateNotFound
from .ai_models import ContextType, ConversationContext


class PromptEngine:
    """提示词引擎"""

    def __init__(self, templates_dir: str):
        self.templates_dir = Path(templates_dir)
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["truncate_smart"] = self._truncate_smart
        self.env.filters["format_datetime"] = self._format_datetime
        self.env.filters["extract_mentions"] = self._extract_mentions
        self._template_cache: Dict[str, Template] = {}
        self.templates_dir.mkdir(parents=True, exist_ok=True)

    def _truncate_smart(self, text: str, length: int = 100, suffix: str = "...") -> str:
        """截断文本"""
        if len(text) <= length:
            return text
        truncated = text[:length]
        last_space = truncated.rfind(" ")
        if last_space > length * 0.8:  # 如果空格位置合理
            truncated = truncated[:last_space]

        return truncated + suffix

    def _format_datetime(self, dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
        """格式化日期时间"""
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt)
            except ValueError:
                return dt
        return dt.strftime(format_str)

    def _extract_mentions(self, text: str) -> List[str]:
        """提取@提及"""
        import re
        return re.findall(r"@([\w-]+)", text)

    def get_template(self, template_name: str) -> Optional[Template]:
        """获取模板"""
        if template_name in self._template_cache:
            return self._template_cache[template_name]

        try:
            template = self.env.get_template(template_name)
            self._template_cache[template_name] = template
            return template
        except TemplateNotFound:
            print(f"模板未找到: {template_name}")
            return None

    def render_system_prompt(self, context: ConversationContext, **kwargs) -> str:
        """渲染系统提示词"""
        # 根据上下文类型选择模板
        template_map = {
            ContextType.QQ_GROUP: "qq_group.j2",
            ContextType.QQ_PRIVATE: "qq_private.j2",
            ContextType.GITHUB_PR: "github_pr.j2",
            ContextType.GITHUB_ISSUE: "github_issue.j2",
            ContextType.GITHUB_COMMENT: "github_comment.j2",
        }

        # 基础系统模板
        system_template = self.get_template("system.j2")
        context_template_name = template_map.get(context.context_type)
        context_template = None
        if context_template_name:
            context_template = self.get_template(context_template_name)
        # 准备模板变量
        template_vars = self._prepare_template_vars(context, **kwargs)
        system_prompt = system_template.render(**template_vars)
        # 如果有上下文特定模板, 追加渲染
        if context_template:
            context_prompt = context_template.render(**template_vars)
            system_prompt = f"{system_prompt}\n\n{context_prompt}"

        return system_prompt

    def render_custom_prompt(self, template_name: str, **kwargs) -> str:
        """渲染自定义提示词"""
        template = self.get_template(template_name)
        if not template:
            return f"模板 {template_name} 未找到"

        return template.render(**kwargs)

    def _prepare_template_vars(self, context: ConversationContext, **kwargs) -> Dict[str, Any]:
        """准备模板变量"""
        vars_dict = {
            "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "context_type": context.context_type.value,
            "context_id": context.context_id,
            "repository": context.repository,
            "issue_or_pr_id": context.issue_or_pr_id,
            "group_id": context.group_id,
            "user_id": context.user_id,
            "message_count": context.get_message_count(),
            "conversation_history": context.get_context_summary(),
            "recent_messages": context.get_recent_messages(5),
            "metadata": context.metadata,
        }

        vars_dict.update(kwargs)

        return vars_dict

    def create_template(self, template_name: str, content: str) -> bool:
        """创建新模板"""
        try:
            template_path = self.templates_dir / template_name
            with open(template_path, "w", encoding="utf-8") as f:
                f.write(content)
            if template_name in self._template_cache:
                del self._template_cache[template_name]

            return True
        except Exception as e:
            print(f"创建模板失败: {e}")
            return False

    def list_templates(self) -> List[str]:
        """列出所有模板"""
        try:
            return [f.name for f in self.templates_dir.glob("*.j2")]
        except Exception:
            return []

    def validate_template(self, template_name: str) -> tuple[bool, Optional[str]]:
        """验证模板语法"""
        try:
            template = self.get_template(template_name)
            if not template:
                return False, "模板未找到"
            template.render()
            return True, None
        except Exception as e:
            return False, str(e)

    def reload_templates(self):
        """重新加载所有模板"""
        self._template_cache.clear()
        # Jinja2会自动重新加载模板文件


class PromptManager:
    """提示词管理器"""

    def __init__(self, templates_dir: str):
        self.engine = PromptEngine(templates_dir)
        self.prompt_configs: Dict[str, Dict[str, Any]] = {}
        self._load_prompt_configs()

    def _load_prompt_configs(self):
        """加载提示词配置"""
        config_file = Path(self.engine.templates_dir) / "config.json"
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    self.prompt_configs = json.load(f)
            except Exception as e:
                print(f"加载提示词配置失败: {e}")

    def save_prompt_configs(self):
        """保存提示词配置"""
        config_file = Path(self.engine.templates_dir) / "config.json"
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(self.prompt_configs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存提示词配置失败: {e}")

    def get_prompt_for_context(self, context: ConversationContext, **kwargs) -> str:
        """为特定上下文获取提示词"""
        # 检查是否有自定义配置
        context_key = f"{context.context_type.value}_{context.context_id}"
        if context_key in self.prompt_configs:
            config = self.prompt_configs[context_key]
            if "custom_template" in config:
                return self.engine.render_custom_prompt(config["custom_template"], **kwargs)
        return self.engine.render_system_prompt(context, **kwargs)

    def set_custom_prompt(self, context_id: str, context_type: ContextType, template_name: str):
        """为特定上下文设置自定义提示词"""
        context_key = f"{context_type.value}_{context_id}"
        self.prompt_configs[context_key] = {
            "custom_template": template_name,
            "created_at": datetime.now().isoformat(),
        }
        self.save_prompt_configs()

    def remove_custom_prompt(self, context_id: str, context_type: ContextType):
        """移除自定义提示词配置"""
        context_key = f"{context_type.value}_{context_id}"
        if context_key in self.prompt_configs:
            del self.prompt_configs[context_key]
            self.save_prompt_configs()

    def create_prompt_template(self, name: str, content: str) -> bool:
        """创建提示词模板"""
        return self.engine.create_template(name, content)

    def list_available_templates(self) -> List[str]:
        """列出可用模板"""
        return self.engine.list_templates()

    def validate_template_syntax(self, template_name: str) -> tuple[bool, Optional[str]]:
        """验证模板语法"""
        return self.engine.validate_template(template_name)


# 全局提示词管理器实例
_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager(templates_dir: str = None) -> PromptManager:
    """获取提示词管理器实例"""
    global _prompt_manager

    if _prompt_manager is None:
        if templates_dir is None:
            # 默认模板目录
            current_dir = Path(__file__).parent
            templates_dir = str(current_dir / "prompts")

        _prompt_manager = PromptManager(templates_dir)

    return _prompt_manager


def cleanup_prompt_manager():
    """清理提示词管理器"""
    global _prompt_manager
    _prompt_manager = None
