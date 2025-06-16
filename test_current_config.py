#!/usr/bin/env python3
"""
Test the current config to make sure it loads properly.
"""

import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))


def test_config_loading():
    """Test that the current config loads without errors."""
    print("=== TESTING CURRENT CONFIG ===")

    try:
        print("\n1. Testing BookingDetails...")
        from scheduler.config import BookingDetails

        booking_details = BookingDetails()
        print("✅ BookingDetails loaded successfully")
        print(f"   Base URL: {booking_details.base_url}")
        print(f"   Owner ID: {booking_details.owner_id}")
        print(f"   Selected resource IDs: {booking_details.selected_resource_ids}")
        print(f"   Resource IDs to book: {booking_details.resource_ids_to_book}")

        print("\n2. Testing LoginDetails...")
        from scheduler.config import LoginDetails

        try:
            login_details = LoginDetails()
            print("✅ LoginDetails loaded successfully")
            print(f"   Username: {login_details.uzh_username}")
            print(f"   Has password: {'Yes' if login_details.uzh_password else 'No'}")
            print(
                f"   Has TOTP secret: {'Yes' if login_details.uzh_totp_secret else 'No'}"
            )
        except Exception as e:
            print(f"❌ LoginDetails failed: {e}")
            print("   This is expected if .env file is not set up")

        print("\n3. Testing BookingConstants...")
        from scheduler.config import BookingConstants

        constants = BookingConstants()
        print("✅ BookingConstants loaded successfully")
        print(f"   Default timeout: {constants.DEFAULT_TIMEOUT}")
        print(f"   Timezone: {constants.TIMEZONE}")

        print("\n4. Testing amain imports...")
        try:
            from scheduler.amain import RESOURCE_IDS_TO_BOOK, OWNER_ID

            print("✅ amain imports successful")
            print(f"   Resource IDs to book: {RESOURCE_IDS_TO_BOOK}")
            print(f"   Owner ID: {OWNER_ID}")
        except Exception as e:
            print(f"❌ amain import failed: {e}")

    except Exception as e:
        print(f"❌ Config loading failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_config_loading()
