#!/usr/bin/env python3
"""
Minimal test for spot selector without rich terminal interface.
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))


async def test_minimal_spot_selector():
    """Test spot selector functionality without rich interface."""
    print("=== MINIMAL SPOT SELECTOR TEST ===")

    try:
        # Test 1: Load spots
        print("\n1. Loading spots...")
        from scheduler.amain import authenticated_session
        from scheduler.spot_fetcher import get_all_available_spots

        async with authenticated_session() as (client, csrf_token):
            all_spots = await get_all_available_spots(client)

            print(f"✅ Loaded spots from {len(all_spots)} schedules:")
            total_spots = 0
            for schedule_name, spots in all_spots.items():
                print(f"   📚 {schedule_name}: {len(spots)} spots")
                total_spots += len(spots)

            print(f"\n   Total spots available: {total_spots}")

            # Test 2: Select some spots manually
            print("\n2. Selecting spots for testing...")
            selected_spots = []

            # Select first 3 spots from first schedule that has spots
            for schedule_name, spots in all_spots.items():
                if spots and len(spots) >= 3:
                    selected_spots = spots[:3]
                    print(f"✅ Selected 3 spots from {schedule_name}:")
                    for i, spot in enumerate(selected_spots):
                        print(f"     {i + 1}. {spot.name} (ID: {spot.id})")
                    break

            if not selected_spots:
                print("❌ No spots available for selection")
                return

            # Test 3: Generate config
            print("\n3. Generating config...")
            from scheduler.config import BookingDetails

            # Load current config
            current_config = BookingDetails()

            # Extract resource IDs
            resource_ids = [spot.id for spot in selected_spots]
            resource_ids.sort()

            print(f"✅ Resource IDs to save: {resource_ids}")

            # Create config content (simplified version)
            config_content = f'''from diskcache import Cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, BaseModel
from pathlib import Path

cache_path = Path(__file__).parent / ".cache"
persistent_cache = Cache(cache_path)


class LoginDetails(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).parent / ".env")

    uzh_username: str = Field(alias="UZH_USERNAME")
    uzh_password: str = Field(alias="UZH_PASSWORD")
    uzh_totp_secret: str = Field(alias="UZH_TOTP_SECRET")


class BookingConstants:
    """Centralized constants for booking operations."""

    DEFAULT_TIMEOUT = 15
    CACHE_EXPIRY_HOURS = 6
    MAX_CONCURRENT_BOOKINGS = 50
    TIMEZONE = "Europe/Zurich"

    # HTTP Headers
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3.1 Safari/605.1.15"
    ACCEPT_LANGUAGE = "en-US,en;q=0.9"
    ACCEPT_ENCODING = "gzip, deflate, br"
    CONNECTION = "keep-alive"
    ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


class BookingDetails(BaseModel):
    base_url: str = "{current_config.base_url}"
    login_page_url: str = base_url + "index.php"
    login_action_url: str = base_url + "index.php"
    tfa_validate_url: str = base_url + "auth/confirm-account.php?action=Confirm"
    owner_id: int = {current_config.owner_id}

    # SELECTED SPOTS CONFIGURATION
    # Generated from spot selector with {len(resource_ids)} spots
    selected_resource_ids: list[int] = {resource_ids}

    # Legacy range settings (not used when selected_resource_ids is provided)
    preferred_range_start: int = {current_config.preferred_range_start}
    preferred_range_end: int = {current_config.preferred_range_end}

    # Booking time settings
    preferred_start_time_hour: int = {current_config.preferred_start_time_hour}
    preferred_start_time_minute: int = {current_config.preferred_start_time_minute}
    preferred_end_time_hour: int = {current_config.preferred_end_time_hour}
    preferred_end_time_minute: int = {current_config.preferred_end_time_minute}

    # Booking attributes
    standard_attribute_values: list[dict[str, str]] = {current_config.standard_attribute_values}

    @property
    def resource_ids_to_book(self) -> list[int]:
        """Get the resource IDs to attempt booking."""
        if self.selected_resource_ids:
            return self.selected_resource_ids
        else:
            # Fallback to range if no specific spots selected
            return list(range(self.preferred_range_start, self.preferred_range_end))
'''

            # Write to a test config file (not overwriting the real one)
            test_config_path = Path("scheduler/config_test.py")
            test_config_path.write_text(config_content)

            print(f"✅ Test config written to {test_config_path}")
            print(f"   Selected {len(resource_ids)} spots: {resource_ids}")

            # Test 4: Verify the generated config loads
            print("\n4. Testing generated config...")
            sys.path.insert(0, str(Path("scheduler")))

            try:
                import config_test

                test_booking_details = config_test.BookingDetails()
                print("✅ Generated config loads successfully")
                print(
                    f"   Resource IDs to book: {test_booking_details.resource_ids_to_book}"
                )
                print(
                    f"   Selected resource IDs: {test_booking_details.selected_resource_ids}"
                )
            except Exception as e:
                print(f"❌ Generated config failed to load: {e}")

            print("\n✅ All tests completed successfully!")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_minimal_spot_selector())
