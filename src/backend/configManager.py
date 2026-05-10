# configManager.py
# Under the MIT License.

import yaml

class ConfigManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> dict:
        with open(self.config_path, 'r') as file:
            return yaml.safe_load(file)

    def get_instances_folder(self) -> str:
        return self.config.get('instancesFolder', '')

    def get_status_channel_id(self) -> int:
        return self.config.get('statusChannelID', 0)

    def get_update_interval(self) -> int:
        return self.config.get('updateInerval', 30)

    def get_instances(self) -> dict:
        return self.config.get('instances', {})