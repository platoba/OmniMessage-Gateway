"""
Tests for CLI
"""

import json
import os
import pytest
import tempfile
from unittest.mock import AsyncMock, patch, MagicMock

from gateway.cli import create_parser, main


class TestCLIParser:
    def test_send_command(self):
        parser = create_parser()
        args = parser.parse_args(["send", "telegram", "123456", "Hello World"])
        assert args.command == "send"
        assert args.channel == "telegram"
        assert args.target == "123456"
        assert args.text == "Hello World"

    def test_send_with_options(self):
        parser = create_parser()
        args = parser.parse_args([
            "send", "email", "test@example.com", "Hi",
            "--subject", "Test Subject",
            "--priority", "8",
        ])
        assert args.subject == "Test Subject"
        assert args.priority == 8

    def test_broadcast_command(self):
        parser = create_parser()
        args = parser.parse_args([
            "broadcast", "Hello all",
            "--targets", '[{"channel":"telegram","target":"123"}]',
        ])
        assert args.command == "broadcast"
        assert args.text == "Hello all"

    def test_batch_command(self):
        parser = create_parser()
        args = parser.parse_args(["batch", "messages.json", "--dry-run"])
        assert args.command == "batch"
        assert args.file == "messages.json"
        assert args.dry_run is True

    def test_stats_command(self):
        parser = create_parser()
        args = parser.parse_args(["stats", "--hours", "48", "--format", "json"])
        assert args.command == "stats"
        assert args.hours == 48
        assert args.format == "json"

    def test_history_command(self):
        parser = create_parser()
        args = parser.parse_args([
            "history", "--channel", "telegram", "--status", "sent", "--limit", "50"
        ])
        assert args.command == "history"
        assert args.channel == "telegram"
        assert args.status == "sent"
        assert args.limit == 50

    def test_templates_list(self):
        parser = create_parser()
        args = parser.parse_args(["templates", "list"])
        assert args.command == "templates"
        assert args.tmpl_action == "list"

    def test_templates_add(self):
        parser = create_parser()
        args = parser.parse_args(["templates", "add", "welcome", "Hello {{ name }}!"])
        assert args.tmpl_action == "add"
        assert args.name == "welcome"
        assert args.template_str == "Hello {{ name }}!"

    def test_schedule_add(self):
        parser = create_parser()
        args = parser.parse_args([
            "schedule", "add", "telegram", "123", "Hi",
            "--delay", "300",
        ])
        assert args.sched_action == "add"
        assert args.channel == "telegram"
        assert args.delay == 300

    def test_schedule_list(self):
        parser = create_parser()
        args = parser.parse_args(["schedule", "list"])
        assert args.sched_action == "list"

    def test_schedule_cancel(self):
        parser = create_parser()
        args = parser.parse_args(["schedule", "cancel", "some-id"])
        assert args.sched_action == "cancel"
        assert args.entry_id == "some-id"

    def test_channels_command(self):
        parser = create_parser()
        args = parser.parse_args(["channels"])
        assert args.command == "channels"

    def test_version_command(self):
        parser = create_parser()
        args = parser.parse_args(["version"])
        assert args.command == "version"

    def test_no_command(self):
        parser = create_parser()
        args = parser.parse_args([])
        assert args.command is None


class TestCLIExecution:
    def test_version(self, capsys):
        main(["version"])
        captured = capsys.readouterr()
        assert "OmniMessage Gateway" in captured.out

    def test_channels(self, capsys):
        main(["channels"])
        captured = capsys.readouterr()
        assert "Available Channels" in captured.out

    def test_stats_empty(self, capsys):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            main(["--db", db_path, "stats"])
            captured = capsys.readouterr()
            assert "Statistics" in captured.out
        finally:
            os.unlink(db_path)

    def test_stats_json(self, capsys):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            main(["--db", db_path, "stats", "--format", "json"])
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert "total" in data
        finally:
            os.unlink(db_path)

    def test_history_empty(self, capsys):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            main(["--db", db_path, "history"])
            captured = capsys.readouterr()
            assert "History" in captured.out
        finally:
            os.unlink(db_path)

    def test_templates_list(self, capsys):
        main(["templates", "list"])
        captured = capsys.readouterr()
        assert "Templates" in captured.out

    def test_batch_dry_run(self, capsys):
        # 创建临时 JSON 文件
        records = [
            {"channel": "telegram", "target": "123", "text": "Hello 1"},
            {"channel": "discord", "target": "456", "text": "Hello 2"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(records, f)
            path = f.name
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db:
                db_path = db.name
            main(["--db", db_path, "batch", path, "--dry-run"])
            captured = capsys.readouterr()
            assert "Loaded 2 messages" in captured.out
            assert "Dry run" in captured.out
        finally:
            os.unlink(path)
            os.unlink(db_path)

    def test_no_command_shows_help(self, capsys):
        main([])
        captured = capsys.readouterr()
        assert "usage" in captured.out.lower() or "OmniMessage" in captured.out
