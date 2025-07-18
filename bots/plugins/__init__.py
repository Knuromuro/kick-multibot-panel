"""Plugin system for KickBot."""

from typing import Protocol


class IBot(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def status(self) -> str: ...


plugins = {}


def register(name: str, plugin: IBot) -> None:
    plugins[name] = plugin
