from . import register
from bots.instance import BotInstance


class SeleniumAdapter:
    def __init__(self, instance: BotInstance):
        self.instance = instance

    def start(self) -> None:
        self.instance.login()

    def stop(self) -> None:
        if self.instance.ws:
            self.instance.ws.close()

    def status(self) -> str:
        return (
            "online" if self.instance.ws and not self.instance.ws.closed else "offline"
        )


register("selenium", SeleniumAdapter)
