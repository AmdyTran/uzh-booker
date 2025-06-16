#!/usr/bin/env python3
"""
Debug script for spot selector - step by step testing without pretty terminal.
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))


async def debug_step_by_step():
    """Debug the spot selector step by step."""
    print("=== DEBUGGING SPOT SELECTOR ===")

    try:
        # Step 1: Test authentication
        print("\n1. Testing authentication...")
        from scheduler.amain import authenticated_session

        async with authenticated_session() as (client, csrf_token):
            print("✅ Authentication successful")
            print(f"   Client: {type(client)}")
            print(f"   CSRF token: {csrf_token[:10]}...")

            # Step 2: Test spot fetching
            print("\n2. Testing spot fetching...")
            from scheduler.spot_fetcher import fetch_spots_for_schedule

            # Test with schedule 8 (Medizin Careum - Sockelgeschoss)
            spots = await fetch_spots_for_schedule(client, 8)
            print(f"✅ Found {len(spots)} spots in schedule 8")

            if spots:
                print("   First 5 spots:")
                for i, spot in enumerate(spots[:5]):
                    print(f"     {i + 1}. {spot.name} (ID: {spot.id})")

            # Step 3: Test config generation
            print("\n3. Testing config generation...")
            from create_config import SpotSelector

            selector = SpotSelector()

            # Manually select a few spots for testing
            if len(spots) >= 3:
                selector.selected_spots = spots[:3]
                print(f"✅ Selected {len(selector.selected_spots)} spots for testing:")
                for spot in selector.selected_spots:
                    print(f"     - {spot.name} (ID: {spot.id})")

                # Test config generation
                print("\n4. Testing config file generation...")
                await selector._write_config_file()
                print("✅ Config generation completed")
            else:
                print("❌ Not enough spots to test config generation")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_step_by_step())
