from __future__ import annotations

import pytest

from app.todo import create_todo, mark_done


def test_create_todo() -> None:
    todo = create_todo("learn agent")
    assert todo.title == "learn agent"
    assert todo.done is False


def test_create_todo_empty_title() -> None:
    with pytest.raises(ValueError):
        create_todo("")


def test_mark_done() -> None:
    todo = create_todo("learn agent")
    mark_done(todo)
    assert todo.done is True
