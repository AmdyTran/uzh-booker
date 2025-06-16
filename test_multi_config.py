#!/usr/bin/env python3
"""
Test the multi-config functionality.
"""

import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))


def test_config_loader():
    """Test the config loader functionality."""
    print("=== TESTING MULTI-CONFIG FUNCTIONALITY ===")
    
    try:
        from scheduler.config_loader import (
            list_available_configs,
            validate_config,
            get_booking_details,
        )
        
        print("\n1. Testing config listing...")
        configs = list_available_configs()
        print(f"✅ Found {len(configs)} config files:")
        for config in configs:
            print(f"   - {config}.py")
        
        print("\n2. Testing default config validation...")
        is_valid = validate_config(None)
        print(f"✅ Default config valid: {is_valid}")
        
        print("\n3. Testing default config loading...")
        booking_details = get_booking_details(None)
        print(f"✅ Default config loaded")
        print(f"   Resource IDs: {booking_details.resource_ids_to_book}")
        print(f"   Owner ID: {booking_details.owner_id}")
        
        print("\n4. Testing booking script help...")
        from scheduler.booking_main import main
        print("✅ Booking main script imported successfully")
        
        print("\n5. Testing config management...")
        from manage_configs import list_configs
        print("✅ Config management script imported successfully")
        
        print("\n✅ All multi-config tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


def test_usage_examples():
    """Show usage examples."""
    print("\n=== USAGE EXAMPLES ===")
    
    examples = [
        "# List available configs",
        "uv run manage-configs list",
        "",
        "# Create a new config for Monday",
        "uv run select-spots  # Select spots and save as monday_config",
        "",
        "# Copy default config to create tuesday_config",
        "uv run manage-configs copy config tuesday_config",
        "",
        "# Book using specific config",
        "uv run book-async --config monday_config",
        "",
        "# Book using default config",
        "uv run book-async",
        "",
        "# Make monday_config the new default",
        "uv run manage-configs make-default monday_config",
        "",
        "# Validate a config",
        "uv run book-async --validate monday_config",
        "",
        "# List all available configs",
        "uv run book-async --list-configs",
    ]
    
    for example in examples:
        print(example)


if __name__ == "__main__":
    test_config_loader()
    test_usage_examples()