"""
Tests for gateway.templates - Template engine
"""

import os
import pytest
import tempfile

from gateway.templates import TemplateEngine


class TestTemplateEngine:
    def test_register_and_render(self):
        engine = TemplateEngine()
        engine.register("greet", "Hello, {{ name }}!")
        result = engine.render("greet", {"name": "Alice"})
        assert result == "Hello, Alice!"

    def test_render_with_missing_var(self):
        engine = TemplateEngine()
        engine.register("tmpl", "Hi {{ name }}, you have {{ count }} messages")
        result = engine.render("tmpl", {"name": "Bob"})
        assert "Bob" in result

    def test_render_string(self):
        engine = TemplateEngine()
        result = engine.render_string("Order #{{ id }}: {{ status }}", {"id": 42, "status": "shipped"})
        assert result == "Order #42: shipped"

    def test_unregister(self):
        engine = TemplateEngine()
        engine.register("temp", "data")
        assert engine.unregister("temp") is True
        assert engine.unregister("nonexistent") is False

    def test_has_template(self):
        engine = TemplateEngine()
        engine.register("exists", "yes")
        assert engine.has_template("exists") is True
        assert engine.has_template("nope") is False

    def test_list_templates(self):
        engine = TemplateEngine()
        engine.register("a", "template A")
        engine.register("b", "template B")
        templates = engine.list_templates()
        assert "a" in templates["memory"]
        assert "b" in templates["memory"]

    def test_render_not_found(self):
        engine = TemplateEngine()
        with pytest.raises(Exception):  # TemplateNotFound
            engine.render("nonexistent")

    def test_file_templates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpl_path = os.path.join(tmpdir, "welcome.txt")
            with open(tmpl_path, "w") as f:
                f.write("Welcome {{ user }}!")

            engine = TemplateEngine(template_dir=tmpdir)
            result = engine.render("welcome.txt", {"user": "Charlie"})
            assert result == "Welcome Charlie!"
            assert engine.has_template("welcome.txt") is True

    def test_memory_overrides_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpl_path = os.path.join(tmpdir, "msg.txt")
            with open(tmpl_path, "w") as f:
                f.write("FILE version")

            engine = TemplateEngine(template_dir=tmpdir)
            engine.register("msg.txt", "MEMORY version")
            result = engine.render("msg.txt")
            assert result == "MEMORY version"

    def test_complex_template(self):
        engine = TemplateEngine()
        engine.register(
            "order_notification",
            "🛒 Order #{{ order_id }}\n"
            "{% for item in items %}"
            "  - {{ item.name }}: ${{ item.price }}\n"
            "{% endfor %}"
            "Total: ${{ total }}",
        )
        result = engine.render(
            "order_notification",
            {
                "order_id": "ORD-001",
                "items": [
                    {"name": "Widget", "price": "9.99"},
                    {"name": "Gadget", "price": "24.99"},
                ],
                "total": "34.98",
            },
        )
        assert "ORD-001" in result
        assert "Widget" in result
        assert "34.98" in result
