from __future__ import annotations

from file_utils.text import count_lines, read_text, slugify_filename, write_text


def test_write_and_read_text(tmp_path) -> None:
    path = tmp_path / "notes.txt"
    write_text(path, "hello")
    assert read_text(path) == "hello"


def test_count_lines() -> None:
    assert count_lines("") == 0
    assert count_lines("a\nb\nc") == 3


def test_slugify_filename() -> None:
    assert slugify_filename("Sprint Notes.md") == "sprint-notes-md"
    assert slugify_filename("   ") == "untitled"
