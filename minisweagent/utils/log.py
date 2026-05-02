import logging
from pathlib import Path

from rich.logging import RichHandler


logger = logging.getLogger("minisweagent")


def configure_logging() -> logging.Logger:
    """Configure the default mini-swe-agent console logger on demand."""
    logger.setLevel(logging.DEBUG)
    if not any(getattr(handler, "_minisweagent_console_handler", False) for handler in logger.handlers):
        handler = RichHandler(
            show_path=False,
            show_time=False,
            show_level=False,
            markup=True,
        )
        formatter = logging.Formatter("%(name)s: %(levelname)s: %(message)s")
        handler.setFormatter(formatter)
        handler._minisweagent_console_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    return logger


def add_file_handler(path: Path | str, level: int = logging.DEBUG, *, print_path: bool = True) -> None:
    configure_logging()
    handler = logging.FileHandler(path)
    handler.setLevel(level)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    if print_path:
        print(f"Logging to '{path}'")


__all__ = ["add_file_handler", "configure_logging", "logger"]
