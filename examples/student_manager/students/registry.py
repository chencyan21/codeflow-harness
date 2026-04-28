from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Student:
    name: str
    gpa: float = 0.0
    active: bool = True


class StudentRegistry:
    def __init__(self) -> None:
        self._students: dict[str, Student] = {}

    def add_student(self, name: str, gpa: float = 0.0) -> Student:
        if not name.strip():
            raise ValueError("student name is required")
        if name in self._students:
            raise ValueError(f"student already exists: {name}")
        student = Student(name=name, gpa=gpa)
        self._students[name] = student
        return student

    def get_student(self, name: str) -> Student:
        try:
            return self._students[name]
        except KeyError as exc:
            raise KeyError(f"student not found: {name}") from exc

    def update_gpa(self, name: str, gpa: float) -> Student:
        student = self.get_student(name)
        student.gpa = gpa
        return student

    def deactivate(self, name: str) -> Student:
        student = self.get_student(name)
        student.active = False
        return student

    def active_students(self) -> list[Student]:
        return sorted(
            (student for student in self._students.values() if student.active),
            key=lambda student: student.name,
        )

    def class_average(self) -> float:
        if not self._students:
            return 0.0
        return sum(student.gpa for student in self._students.values()) / len(self._students)
