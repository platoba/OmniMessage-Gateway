"""
消息模板引擎 - Jinja2
"""

import os
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader, BaseLoader, TemplateNotFound


class StringLoader(BaseLoader):
    """从字典加载模板字符串"""

    def __init__(self, templates: Dict[str, str]):
        self.templates = templates

    def get_source(self, environment: Environment, template: str):
        if template in self.templates:
            source = self.templates[template]
            return source, template, lambda: True
        raise TemplateNotFound(template)


class TemplateEngine:
    """
    消息模板引擎
    支持:
    - 文件模板 (从目录加载)
    - 内存模板 (运行时注册)
    - 字符串直接渲染
    """

    def __init__(self, template_dir: Optional[str] = None):
        self._string_templates: Dict[str, str] = {}
        self._template_dir = template_dir

        # 文件系统环境 (如果目录存在)
        if template_dir and os.path.isdir(template_dir):
            self._file_env = Environment(
                loader=FileSystemLoader(template_dir),
                autoescape=False,
            )
        else:
            self._file_env = None

        # 字符串模板环境
        self._string_env = Environment(
            loader=StringLoader(self._string_templates),
            autoescape=False,
        )

    def register(self, name: str, template_str: str) -> None:
        """注册内存模板"""
        self._string_templates[name] = template_str

    def unregister(self, name: str) -> bool:
        """移除内存模板"""
        if name in self._string_templates:
            del self._string_templates[name]
            return True
        return False

    def list_templates(self) -> Dict[str, list]:
        """列出所有可用模板"""
        result: Dict[str, list] = {
            "memory": list(self._string_templates.keys()),
            "files": [],
        }
        if self._file_env:
            result["files"] = self._file_env.list_templates()
        return result

    def render(self, template_name: str, variables: Dict[str, Any] = None) -> str:
        """
        渲染模板
        优先查找内存模板, 然后查找文件模板
        """
        variables = variables or {}

        # 先查内存模板
        if template_name in self._string_templates:
            tmpl = self._string_env.get_template(template_name)
            return tmpl.render(**variables)

        # 再查文件模板
        if self._file_env:
            try:
                tmpl = self._file_env.get_template(template_name)
                return tmpl.render(**variables)
            except TemplateNotFound:
                pass

        raise TemplateNotFound(template_name)

    def render_string(self, template_str: str, variables: Dict[str, Any] = None) -> str:
        """直接渲染模板字符串"""
        variables = variables or {}
        env = Environment(autoescape=False)
        tmpl = env.from_string(template_str)
        return tmpl.render(**variables)

    def has_template(self, name: str) -> bool:
        """检查模板是否存在"""
        if name in self._string_templates:
            return True
        if self._file_env:
            try:
                self._file_env.get_template(name)
                return True
            except TemplateNotFound:
                return False
        return False
