from __future__ import annotations

import pytest

from students.registry import StudentRegistry


def test_add_and_get_student() -> None:
    registry = StudentRegistry()
    student = registry.add_student("Ada", 3.8)
    assert registry.get_student("Ada") is student
    assert student.gpa == 3.8


def test_duplicate_student_rejected() -> None:
    registry = StudentRegistry()
    registry.add_student("Ada")
    with pytest.raises(ValueError):
        registry.add_student("Ada")


def test_active_students_are_sorted() -> None:
    registry = StudentRegistry()
    registry.add_student("Grace")
    registry.add_student("Ada")
    registry.deactivate("Grace")
    assert [student.name for student in registry.active_students()] == ["Ada"]


def test_class_average() -> None:
    registry = StudentRegistry()
    registry.add_student("Ada", 4.0)
    registry.add_student("Grace", 3.0)
    assert registry.class_average() == 3.5
