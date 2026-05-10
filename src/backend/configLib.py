# Based on the work of my other project, Amethyst.
# Under the MIT License.

import os
from typing import Dict, Union

def parseConfig(config_path: str) -> Dict[str, Union[str, bool]]:
    """
    Parses a .config file and returns a dict of config settings
    
    Supports boolean conversion for 'true'/'false' strings.
    Ignores comments (#) and blank lines.
    """
    config = {}

    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Config file not found at {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            if "=" not in line:
                continue  #it's malformed
            
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            #wow! python made True and False uppercase, even when the norm is lowercase!
            if value.lower() == "true":
                value = True
            elif value.lower() == "false":
                value = False

            config[key] = value
    
    return config

def getConfigVal(config: dict, key: str, default=None, value_type=None):
    """
    Retrieve a config value requested by key from config dict.
    
    :param config: The dictionary returned by parse_geode_config.
    :param key: The config key to look for.
    :param default: Value to return if key not found.
    :param value_type: Cast the value to this type if specified ('bool', 'int', 'str', etc.).
    """
    val = config.get(key, default)
    if val is None:
        return val

    if value_type:
        try:
            if value_type == bool:
                if isinstance(val, bool):
                    return val
                val_lower = str(val).lower()
                if val_lower in ("true", "yes", "1"):
                    return True
                elif val_lower in ("false", "no", "0"):
                    return False
                else:
                    return bool(val) #fallback
            else:
                return value_type(val)
        except Exception:
            return default
    return val

def parseServerProperties(path: str) -> dict:
    props = {}

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            props[key.strip()] = value.strip()
    # print(f"Parsed server.properties: {props}")
    return props


