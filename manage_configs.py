#!/usr/bin/env python3
"""
Config management utility for UZH booking system.

This script helps manage multiple booking configurations.
"""

import sys
from pathlib import Path
from shutil import copy2

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from scheduler.config_loader import list_available_configs, validate_config


def list_configs():
    """List all available config files."""
    configs = list_available_configs()
    print("📋 Available config files:")

    if not configs:
        print("  No config files found")
        return

    for config in configs:
        config_name = config if config != "config" else None
        status = "✅" if validate_config(config_name) else "❌"
        is_default = " (default)" if config == "config" else ""
        print(f"  {status} {config}.py{is_default}")


def copy_config(source: str, target: str):
    """Copy a config file to a new name."""
    source_path = Path(f"scheduler/{source}.py")
    target_path = Path(f"scheduler/{target}.py")

    if not source_path.exists():
        print(f"❌ Source config not found: {source_path}")
        return False

    if target_path.exists():
        response = input(f"Target config {target_path} exists. Overwrite? (y/N): ")
        if response.lower() != "y":
            print("❌ Cancelled")
            return False

    try:
        copy2(source_path, target_path)
        print(f"✅ Copied {source_path} to {target_path}")
        return True
    except Exception as e:
        print(f"❌ Copy failed: {e}")
        return False


def make_default(config_name: str):
    """Make a named config the default config.py."""
    if config_name == "config":
        print("❌ Config is already the default")
        return False

    source_path = Path(f"scheduler/{config_name}.py")
    target_path = Path("scheduler/config.py")

    if not source_path.exists():
        print(f"❌ Config not found: {source_path}")
        return False

    # Backup current default if it exists
    if target_path.exists():
        backup_path = Path("scheduler/config_backup.py")
        copy2(target_path, backup_path)
        print(f"📋 Backed up current config to {backup_path}")

    try:
        copy2(source_path, target_path)
        print(f"✅ Made {config_name} the default config")
        return True
    except Exception as e:
        print(f"❌ Failed to make default: {e}")
        return False


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("📋 Config Management Utility")
        print()
        print("Usage:")
        print("  python manage_configs.py list")
        print("  python manage_configs.py copy <source> <target>")
        print("  python manage_configs.py make-default <config_name>")
        print()
        print("Examples:")
        print("  python manage_configs.py list")
        print("  python manage_configs.py copy config monday_config")
        print("  python manage_configs.py make-default monday_config")
        return

    command = sys.argv[1]

    if command == "list":
        list_configs()

    elif command == "copy":
        if len(sys.argv) != 4:
            print("❌ Usage: python manage_configs.py copy <source> <target>")
            return
        source, target = sys.argv[2], sys.argv[3]
        copy_config(source, target)

    elif command == "make-default":
        if len(sys.argv) != 3:
            print("❌ Usage: python manage_configs.py make-default <config_name>")
            return
        config_name = sys.argv[2]
        make_default(config_name)

    else:
        print(f"❌ Unknown command: {command}")
        print("Available commands: list, copy, make-default")


if __name__ == "__main__":
    main()
