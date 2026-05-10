# This program is part of Nexa, which provides logging capabilities to the codebase, as well as plugins.
# This allows for NexaLogger objects to be instantiated by aspects of the programming language. It all funnels into one direct
# log created by main.
# Under the MIT License.


import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_initialized = False

def _resolve_log_path(log_folder: str) -> Path:
    """
    Generate a unique log file path in the format:
    nexaLog-{MM-DD-YYYY}-{HH-MM-SS}-{n}.log
    The counter suffix is only appended if a collision exists.
    """
    from datetime import datetime

    folder = Path(log_folder)
    folder.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    timestamp = now.strftime("%m-%d-%Y-%H-%M-%S")
    base = f"nexaLog-{timestamp}"

    path = folder / f"{base}.log"
    counter = 0
    while path.exists():
        path = folder / f"{base}-{counter}.log"
        counter += 1

    return path

def setup(config):
    """
    Configure the root Nexa logger from a NexaConfig instance.
    Call once in main.py before anything else.
    """
    global _initialized
    if _initialized:
        return

    level_str   = config.get("logging.level",             "INFO").upper()
    enable_file = config.get("logging.enableFileLogging",  True)
    log_folder  = config.get("logging.logFolder",          "logs")
    max_bytes   = config.get("logging.maxFileSizeMB",      5) * 1024 * 1024
    backups     = config.get("logging.backupCount",        7)
    components  = config.get("logging.components",         {})

    root_level = getattr(logging, level_str, logging.INFO)

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    root = logging.getLogger("Nexa")
    root.setLevel(logging.DEBUG)  # Stay wide open; handlers + children do the filtering
    root.propagate = False

    # --- File handler ---
    if enable_file:
            log_path = _resolve_log_path(log_folder)
    
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setLevel(root_level)
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)

    # --- Console handler ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(root_level)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # --- Per-component levels ---
    for component, comp_level_str in components.items():
        comp_level = getattr(logging, comp_level_str.upper(), root_level)
        logging.getLogger(f"Nexa.{component}").setLevel(comp_level)

    _initialized = True
    root.info(
        "Nexa logger initialised. Level=%s, file=%s",
        level_str,
        f"{log_folder}/nexa.log" if enable_file else "disabled"
    )


def get_logger(name: str) -> logging.Logger:
    """
    Return a named child logger under the Nexa hierarchy.

    Usage:
        logger = nexaLoggerFactory.get_logger("rcon")
        logger.debug("Sent command: /say hello")
        # → [2025-01-04 12:33:01] [DEBUG   ] [Nexa.rcon] Sent command: /say hello
    """
    return logging.getLogger(f"Nexa.{name}")