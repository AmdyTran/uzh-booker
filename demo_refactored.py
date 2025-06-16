#!/usr/bin/env python3
"""
Demo script for the refactored async booking system.

This script demonstrates the improved spam booking functionality with:
- Clean, structured code
- Proper error handling
- Realistic spam booking behavior
- Performance monitoring
"""

import asyncio
import sys
from pathlib import Path
from datetime import date, timedelta

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from scheduler.amain import main_async


async def main():
    """Demo the refactored booking system."""
    print("🚀 REFACTORED ASYNC BOOKING SYSTEM DEMO")
    print("=" * 50)

    print("This demo shows the improved spam booking strategy:")
    print("✨ Structured data classes (BookingRequest, BookingResult)")
    print("⚡ Concurrent spam booking (32 requests simultaneously)")
    print("🛡️  Better error handling and logging")
    print("📊 Performance monitoring and timing")
    print("🎯 Realistic success rates (0-5% expected)")

    print(f"\n📅 Target date: {date.today() + timedelta(days=7)}")
    print("⏰ Time slot: 18:00-18:30 UTC (20:00-20:30 Zurich time)")
    print("📍 Resources: 231-262 (32 total)")

    print("\n🔄 Starting spam booking...")
    print("-" * 30)

    try:
        # Run the main booking function
        await main_async()

        print("-" * 30)
        print("✅ Booking process completed!")

    except Exception as e:
        print(f"❌ Booking failed: {e}")

    print("\n💡 Key improvements in refactored version:")
    print("   🔧 Modular functions with single responsibilities")
    print("   📦 Context managers for resource management")
    print("   🔄 Improved retry logic and session management")
    print("   📊 Enhanced logging and result tracking")
    print("   ⚡ Optimized concurrent spam strategy")


def main_sync():
    """Synchronous entry point for uv run."""
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
