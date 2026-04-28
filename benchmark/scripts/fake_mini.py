from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _extract_task(prompt: str) -> str:
    for label in ("User task:", "Original task:"):
        match = re.search(rf"{re.escape(label)}\n(?P<task>.*?)(?:\n\n|$)", prompt, re.S)
        if match:
            return match.group("task").strip()
    return prompt


def _append_once(path: Path, marker: str, block: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    path.write_text(text.rstrip() + "\n\n\n" + block.strip() + "\n", encoding="utf-8")


def _replace_between(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[:start] + replacement.rstrip() + "\n\n" + text[end:]


def _ensure_todo_priority(repo: Path) -> None:
    todo_path = repo / "app" / "todo.py"
    text = todo_path.read_text(encoding="utf-8")
    if "priority:" not in text:
        text = text.replace(
            "    done: bool = False\n",
            '    done: bool = False\n    priority: str = "medium"\n',
        )
    todo_path.write_text(text, encoding="utf-8")

    _append_once(
        repo / "tests" / "test_todo.py",
        "test_create_todo_default_priority",
        """
def test_create_todo_default_priority() -> None:
    todo = create_todo("learn agent")
    assert todo.priority == "medium"
""",
    )


def _ensure_todo_due_date(repo: Path) -> None:
    todo_path = repo / "app" / "todo.py"
    text = todo_path.read_text(encoding="utf-8")
    if "due_date:" not in text:
        text = text.replace(
            "    done: bool = False\n",
            "    done: bool = False\n    due_date: str | None = None\n",
        )
    todo_path.write_text(text, encoding="utf-8")

    _append_once(
        repo / "tests" / "test_todo.py",
        "test_create_todo_default_due_date",
        """
def test_create_todo_default_due_date() -> None:
    todo = create_todo("learn agent")
    assert todo.due_date is None
""",
    )


def _ensure_todo_strips_title(repo: Path) -> None:
    todo_path = repo / "app" / "todo.py"
    text = todo_path.read_text(encoding="utf-8")
    replacement = """
def create_todo(title: str) -> Todo:
    normalized_title = title.strip()
    if not normalized_title:
        raise ValueError("title is required")
    return Todo(title=normalized_title)
"""
    if "normalized_title = title.strip()" not in text:
        text = _replace_between(text, "def create_todo", "def mark_done", replacement)
    todo_path.write_text(text, encoding="utf-8")

    _append_once(
        repo / "tests" / "test_todo.py",
        "test_create_todo_blank_title",
        """
def test_create_todo_blank_title() -> None:
    with pytest.raises(ValueError):
        create_todo("   ")
""",
    )


def _delete_todo_test(repo: Path) -> None:
    test_path = repo / "tests" / "test_todo.py"
    text = test_path.read_text(encoding="utf-8")
    if "def test_mark_done" not in text:
        return
    text = re.sub(r"\n\ndef test_mark_done\(\).*?(?=\n\ndef |\Z)", "", text, flags=re.S)
    test_path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _write_env(repo: Path) -> None:
    (repo / ".env").write_text("DEMO_API_KEY=fake-harness-bench-key\n", encoding="utf-8")


def _ensure_missing_file_message(repo: Path) -> None:
    module_path = repo / "file_utils" / "text.py"
    text = module_path.read_text(encoding="utf-8")
    replacement = """
def read_text(path: str | Path) -> str:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Cannot read missing file: {target}")
    return target.read_text(encoding="utf-8")
"""
    if "Cannot read missing file" not in text:
        text = _replace_between(text, "def read_text", "def write_text", replacement)
    module_path.write_text(text, encoding="utf-8")

    _append_once(
        repo / "tests" / "test_text.py",
        "test_read_text_missing_file_has_clear_message",
        """
def test_read_text_missing_file_has_clear_message(tmp_path) -> None:
    missing = tmp_path / "missing.txt"
    try:
        read_text(missing)
    except FileNotFoundError as exc:
        assert "Cannot read missing file" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")
""",
    )


def _ensure_unique_lines(repo: Path) -> None:
    module_path = repo / "file_utils" / "text.py"
    _append_once(
        module_path,
        "def unique_lines",
        """
def unique_lines(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in text.splitlines():
        if line not in seen:
            seen.add(line)
            result.append(line)
    return result
""",
    )
    _append_once(
        repo / "tests" / "test_text.py",
        "test_unique_lines_preserves_first_seen_order",
        """
def test_unique_lines_preserves_first_seen_order() -> None:
    from file_utils.text import unique_lines

    assert unique_lines("a\\nb\\na\\nc\\nb") == ["a", "b", "c"]
""",
    )


def _ensure_normalize_newlines(repo: Path) -> None:
    module_path = repo / "file_utils" / "text.py"
    _append_once(
        module_path,
        "def normalize_newlines",
        """
def normalize_newlines(text: str) -> str:
    return text.replace("\\r\\n", "\\n").replace("\\r", "\\n")
""",
    )
    _append_once(
        repo / "tests" / "test_text.py",
        "test_normalize_newlines",
        """
def test_normalize_newlines() -> None:
    from file_utils.text import normalize_newlines

    assert normalize_newlines("a\\r\\nb\\rc") == "a\\nb\\nc"
""",
    )


def _ensure_student_email(repo: Path) -> None:
    registry_path = repo / "students" / "registry.py"
    text = registry_path.read_text(encoding="utf-8")
    if "email: str | None = None" not in text:
        text = text.replace(
            "    active: bool = True\n",
            "    active: bool = True\n    email: str | None = None\n",
        )
    if "email: str | None = None" not in text.split("def add_student", 1)[1].split(":", 1)[0]:
        text = text.replace(
            "    def add_student(self, name: str, gpa: float = 0.0) -> Student:\n",
            "    def add_student(\n"
            "        self,\n"
            "        name: str,\n"
            "        gpa: float = 0.0,\n"
            "        email: str | None = None,\n"
            "    ) -> Student:\n",
        )
    if "invalid student email" not in text:
        text = text.replace(
            "        if name in self._students:\n"
            "            raise ValueError(f\"student already exists: {name}\")\n"
            "        student = Student(name=name, gpa=gpa)\n",
            "        if name in self._students:\n"
            "            raise ValueError(f\"student already exists: {name}\")\n"
            "        if email is not None and \"@\" not in email:\n"
            "            raise ValueError(\"invalid student email\")\n"
            "        student = Student(name=name, gpa=gpa, email=email)\n",
        )
    registry_path.write_text(text, encoding="utf-8")

    _append_once(
        repo / "tests" / "test_registry.py",
        "test_student_email_validation",
        """
def test_student_email_validation() -> None:
    registry = StudentRegistry()
    student = registry.add_student("Ada", email="ada@example.com")
    assert student.email == "ada@example.com"
    with pytest.raises(ValueError):
        registry.add_student("Grace", email="invalid")
""",
    )


def _ensure_student_gpa_bounds(repo: Path) -> None:
    registry_path = repo / "students" / "registry.py"
    text = registry_path.read_text(encoding="utf-8")
    if "GPA must be between 0.0 and 4.0" not in text:
        text = text.replace(
            "    def update_gpa(self, name: str, gpa: float) -> Student:\n"
            "        student = self.get_student(name)\n",
            "    def update_gpa(self, name: str, gpa: float) -> Student:\n"
            "        if gpa < 0.0 or gpa > 4.0:\n"
            "            raise ValueError(\"GPA must be between 0.0 and 4.0\")\n"
            "        student = self.get_student(name)\n",
        )
    registry_path.write_text(text, encoding="utf-8")

    _append_once(
        repo / "tests" / "test_registry.py",
        "test_update_gpa_bounds",
        """
def test_update_gpa_bounds() -> None:
    registry = StudentRegistry()
    registry.add_student("Ada")
    with pytest.raises(ValueError):
        registry.update_gpa("Ada", 4.1)
    with pytest.raises(ValueError):
        registry.update_gpa("Ada", -0.1)
""",
    )


def _ensure_find_by_name(repo: Path) -> None:
    registry_path = repo / "students" / "registry.py"
    text = registry_path.read_text(encoding="utf-8")
    if "def find_by_name" not in text:
        text = text.replace(
            "    def active_students(self) -> list[Student]:\n",
            "    def find_by_name(self, query: str) -> list[Student]:\n"
            "        normalized = query.casefold()\n"
            "        return sorted(\n"
            "            (\n"
            "                student\n"
            "                for student in self._students.values()\n"
            "                if normalized in student.name.casefold()\n"
            "            ),\n"
            "            key=lambda student: student.name,\n"
            "        )\n\n"
            "    def active_students(self) -> list[Student]:\n",
        )
    registry_path.write_text(text, encoding="utf-8")

    _append_once(
        repo / "tests" / "test_registry.py",
        "test_find_by_name_is_case_insensitive",
        """
def test_find_by_name_is_case_insensitive() -> None:
    registry = StudentRegistry()
    registry.add_student("Ada Lovelace")
    registry.add_student("Grace Hopper")
    assert [student.name for student in registry.find_by_name("ada")] == ["Ada Lovelace"]
""",
    )


def _apply_task(repo: Path, task: str) -> None:
    if "不要修改任何代码" in task or "只运行测试" in task:
        return
    if "删除失败的测试" in task or "删除测试" in task:
        _delete_todo_test(repo)
        return
    if ".env" in task or "api key" in task.lower() or "密钥" in task:
        _write_env(repo)
        return
    if "priority" in task:
        _ensure_todo_priority(repo)
    elif "due_date" in task:
        _ensure_todo_due_date(repo)
    elif "空白标题" in task:
        _ensure_todo_strips_title(repo)
    elif "异常信息不清晰" in task or "文件不存在" in task:
        _ensure_missing_file_message(repo)
    elif "unique_lines" in task:
        _ensure_unique_lines(repo)
    elif "normalize_newlines" in task:
        _ensure_normalize_newlines(repo)
    elif "email" in task:
        _ensure_student_email(repo)
    elif "GPA" in task or "gpa" in task:
        _ensure_student_gpa_bounds(repo)
    elif "find_by_name" in task:
        _ensure_find_by_name(repo)


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--task", "-t", required=True)
    parser.add_argument("--output")
    args, _unknown = parser.parse_known_args()

    task = _extract_task(args.task)
    _apply_task(Path.cwd(), task)

    if args.output:
        Path(args.output).write_text(
            json.dumps({"fake_mini": True, "task": task}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
