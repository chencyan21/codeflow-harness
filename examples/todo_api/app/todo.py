from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Todo:
    title: str
    done: bool = False


def create_todo(title: str) -> Todo:
    if not title:
        raise ValueError("title is required")
    return Todo(title=title)


def mark_done(todo: Todo) -> Todo:
    todo.done = True
    return todo
