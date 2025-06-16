"""
Main booking script with config file support.

This script supports multiple config files for different booking scenarios.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scheduler.config_loader import (
    get_booking_details,
    list_available_configs,
    validate_config,
)


async def run_booking_with_config(config_name: str | None = None):
    """
    Run the booking process with the specified config.

    Args:
        config_name: Name of the config file (without .py), or None for default
    """
    try:
        # Validate config first
        if not validate_config(config_name):
            print(f"❌ Invalid config: {config_name or 'default'}")
            return False

        # Load config
        booking_details = get_booking_details(config_name)

        print(f"📋 Using config: {config_name or 'default'}")
        print(f"🎯 Target spots: {booking_details.resource_ids_to_book}")
        print(f"👤 Owner ID: {booking_details.owner_id}")

        # Import and run the main booking function with the loaded config
        # We need to temporarily replace the global config
        import scheduler.amain as amain_module

        # Store original values
        original_booking_details = amain_module.booking_details
        original_resource_ids = amain_module.RESOURCE_IDS_TO_BOOK
        original_owner_id = amain_module.OWNER_ID

        try:
            # Replace with new config
            amain_module.booking_details = booking_details
            amain_module.RESOURCE_IDS_TO_BOOK = booking_details.resource_ids_to_book
            amain_module.OWNER_ID = booking_details.owner_id

            # Run the booking
            await amain_module.main_async()
            return True

        finally:
            # Restore original values
            amain_module.booking_details = original_booking_details
            amain_module.RESOURCE_IDS_TO_BOOK = original_resource_ids
            amain_module.OWNER_ID = original_owner_id

    except Exception as e:
        print(f"❌ Booking failed: {e}")
        return False


def main():
    """Main entry point with argument parsing."""
    parser = argparse.ArgumentParser(
        description="UZH Booking System with multi-config support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                           # Use default config.py
  %(prog)s --config monday_config    # Use monday_config.py
  %(prog)s --list-configs             # List available configs
  %(prog)s --validate monday_config   # Validate a config file
        """,
    )

    parser.add_argument(
        "--config", type=str, help="Config file to use (without .py extension)"
    )

    parser.add_argument(
        "--list-configs", action="store_true", help="List all available config files"
    )

    parser.add_argument(
        "--validate", type=str, help="Validate a config file (without .py extension)"
    )

    args = parser.parse_args()

    if args.list_configs:
        configs = list_available_configs()
        print("📋 Available config files:")
        for config in configs:
            status = (
                "✅"
                if validate_config(config if config != "config" else None)
                else "❌"
            )
            print(f"  {status} {config}.py")
        return

    if args.validate:
        config_name = args.validate if args.validate != "config" else None
        is_valid = validate_config(config_name)
        if is_valid:
            print(f"✅ Config '{args.validate}' is valid")
        else:
            print(f"❌ Config '{args.validate}' is invalid")
        return

    # Run booking
    config_name = args.config if args.config != "config" else None

    try:
        success = asyncio.run(run_booking_with_config(config_name))
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n👋 Cancelled by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
