import json
import os
import logging

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def load_config():
    default_config = {
        "serial_port": "/dev/ttyUSB0",
        "audio_device": "AB13X USB Audio"
    }
    if not os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to create config.json: {e}")
        return default_config
    
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
            for k, v in default_config.items():
                if k not in config:
                    config[k] = v
            return config
    except Exception as e:
        logger.error(f"Failed to load config.json: {e}")
        return default_config
