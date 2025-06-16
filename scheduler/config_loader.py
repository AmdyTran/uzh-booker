"""
Configuration loader that supports multiple config files.

This module allows loading different config files for different booking scenarios.
"""

import importlib.util
from pathlib import Path
from typing import Any

from scheduler.config import BookingDetails, LoginDetails, BookingConstants


def load_config_module(config_name: str | None = None) -> Any:
    """
    Load a configuration module by name.

    Args:
        config_name: Name of the config file (without .py), or None for default

    Returns:
        The loaded config module

    Raises:
        FileNotFoundError: If the config file doesn't exist
        ImportError: If the config file can't be imported
    """
    if config_name is None:
        # Use default config
        from scheduler import config

        return config

    # Load named config
    config_path = Path(__file__).parent / f"{config_name}.py"

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    # Load the module dynamically
    spec = importlib.util.spec_from_file_location(config_name, config_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load config from {config_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def get_booking_details(config_name: str | None = None) -> BookingDetails:
    """
    Get BookingDetails from the specified config.

    Args:
        config_name: Name of the config file (without .py), or None for default

    Returns:
        BookingDetails instance from the config
    """
    config_module = load_config_module(config_name)
    return config_module.BookingDetails()


def get_login_details(config_name: str | None = None) -> LoginDetails:
    """
    Get LoginDetails from the specified config.

    Args:
        config_name: Name of the config file (without .py), or None for default

    Returns:
        LoginDetails instance from the config
    """
    config_module = load_config_module(config_name)
    return config_module.LoginDetails()


def get_booking_constants(config_name: str | None = None) -> type[BookingConstants]:
    """
    Get BookingConstants from the specified config.

    Args:
        config_name: Name of the config file (without .py), or None for default

    Returns:
        BookingConstants class from the config
    """
    config_module = load_config_module(config_name)
    return config_module.BookingConstants


def list_available_configs() -> list[str]:
    """
    List all available config files.

    Returns:
        List of config names (without .py extension)
    """
    scheduler_dir = Path(__file__).parent
    config_files = []

    # Add default config
    if (scheduler_dir / "config.py").exists():
        config_files.append("config")

    # Add named configs
    for config_file in scheduler_dir.glob("*_config.py"):
        config_name = config_file.stem
        config_files.append(config_name)

    return sorted(config_files)


def validate_config(config_name: str | None = None) -> bool:
    """
    Validate that a config file has all required components.

    Args:
        config_name: Name of the config file to validate

    Returns:
        True if config is valid, False otherwise
    """
    try:
        config_module = load_config_module(config_name)

        # Check required classes exist
        required_classes = ["BookingDetails", "LoginDetails", "BookingConstants"]
        for class_name in required_classes:
            if not hasattr(config_module, class_name):
                print(f"Missing required class: {class_name}")
                return False

        # Try to instantiate BookingDetails
        booking_details = config_module.BookingDetails()

        # Check required properties
        required_props = ["resource_ids_to_book", "owner_id", "base_url"]
        for prop in required_props:
            if not hasattr(booking_details, prop):
                print(f"Missing required property: {prop}")
                return False

        return True

    except Exception as e:
        print(f"Config validation failed: {e}")
        return False
