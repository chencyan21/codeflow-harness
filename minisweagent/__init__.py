"""
This file provides:

- Path settings for global config file & relative directories
- Version numbering
- Protocols for the core components of mini-swe-agent.
  By the magic of protocols & duck typing, you can pretty much ignore them,
  unless you want the static type checking.
"""

import os
import sys
from pathlib import Path
from typing import Any, Protocol

from platformdirs import user_config_dir

__version__ = "2.2.8"

package_dir = Path(__file__).resolve().parent


global_config_dir = Path(os.getenv("MSWEA_GLOBAL_CONFIG_DIR") or user_config_dir("mini-swe-agent"))
global_config_file = Path(global_config_dir) / ".env"
_global_config_loaded = False


def ensure_global_config_dir() -> Path:
    """Create and return the mini-SWE-agent global config directory."""
    global_config_dir.mkdir(parents=True, exist_ok=True)
    return global_config_dir


def load_global_config(*, verbose: bool = False, override: bool = False) -> Path:
    """Load the global `.env` file when running a mini-SWE-agent command.

    Importing `minisweagent` stays quiet and filesystem-neutral; command entry
    points call this function explicitly before reading model settings.
    """
    global _global_config_loaded
    from minisweagent.utils.log import configure_logging

    configure_logging()
    ensure_global_config_dir()
    if verbose and not os.getenv("MSWEA_SILENT_STARTUP"):
        from rich.console import Console

        Console().print(
            f"👋 This is [bold green]mini-swe-agent[/bold green] version [bold green]{__version__}[/bold green].\n"
            f"Loading global config from [bold green]'{global_config_file}'[/bold green]",
        )

    import dotenv

    dotenv.load_dotenv(dotenv_path=global_config_file, override=override)
    _global_config_loaded = True

    models_module = sys.modules.get("minisweagent.models")
    stats = getattr(models_module, "GLOBAL_MODEL_STATS", None)
    if stats is not None and hasattr(stats, "reload_limits_from_env"):
        stats.reload_limits_from_env()
    return global_config_file


def __getattr__(name: str) -> Any:
    if name == "logger":
        from minisweagent.utils.log import configure_logging

        return configure_logging()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# === Protocols ===
# You can ignore them unless you want static type checking.


class Model(Protocol):
    """Protocol for language models."""

    config: Any

    def query(self, messages: list[dict[str, str]], **kwargs) -> dict: ...

    def format_message(self, **kwargs) -> dict: ...

    def format_observation_messages(
        self, message: dict, outputs: list[dict], template_vars: dict | None = None
    ) -> list[dict]: ...

    def get_template_vars(self, **kwargs) -> dict[str, Any]: ...

    def serialize(self) -> dict: ...


class Environment(Protocol):
    """Protocol for execution environments."""

    config: Any

    def execute(self, action: dict, cwd: str = "") -> dict[str, Any]: ...

    def get_template_vars(self, **kwargs) -> dict[str, Any]: ...

    def serialize(self) -> dict: ...


class Agent(Protocol):
    """Protocol for agents."""

    config: Any

    def run(self, task: str, **kwargs) -> dict: ...

    def save(self, path: Path | None, *extra_dicts) -> dict: ...


__all__ = [
    "Agent",
    "Model",
    "Environment",
    "package_dir",
    "__version__",
    "global_config_file",
    "global_config_dir",
    "ensure_global_config_dir",
    "load_global_config",
    "logger",
]
