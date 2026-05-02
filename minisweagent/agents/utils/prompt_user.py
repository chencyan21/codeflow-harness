from prompt_toolkit.formatted_text.html import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.shortcuts import PromptSession

from minisweagent import ensure_global_config_dir


class _LazyPromptSession:
    def __init__(self, *, multiline: bool = False) -> None:
        self._multiline = multiline
        self._session: PromptSession | None = None

    def _get(self) -> PromptSession:
        if self._session is None:
            history = FileHistory(ensure_global_config_dir() / "interactive_history.txt")
            self._session = PromptSession(history=history, multiline=self._multiline)
        return self._session

    def prompt(self, *args, **kwargs) -> str:
        return self._get().prompt(*args, **kwargs)


prompt_session = _LazyPromptSession()
_multiline_prompt_session = _LazyPromptSession(multiline=True)


def _multiline_prompt() -> str:
    return _multiline_prompt_session.prompt(
        "",
        bottom_toolbar=HTML(
            "Submit message: <b fg='yellow' bg='black'>Esc, then Enter</b> | "
            "Navigate history: <b fg='yellow' bg='black'>Arrow Up/Down</b> | "
            "Search history: <b fg='yellow' bg='black'>Ctrl+R</b>"
        ),
    )
