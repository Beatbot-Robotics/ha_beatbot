class BeatbotAuthError(Exception):
    pass


class BeatbotConnectionError(Exception):
    pass


class BeatbotAPI:
    async def get_devices(self):
        pass

    async def send_command(self, device_id: str, command: str):
        pass
