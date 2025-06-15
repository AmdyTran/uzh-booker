"""
Script to record VCR cassettes with real HTTP interactions.

This script helps record real API interactions for testing.
Run this once with real credentials to create cassettes.
"""

import subprocess
import sys
from pathlib import Path


def check_credentials():
    """Check if credentials are available."""
    try:
        from scheduler.config import LoginDetails

        settings = LoginDetails()
        if not all(
            [settings.uzh_username, settings.uzh_password, settings.uzh_totp_secret]
        ):
            return False
        return True
    except Exception:
        return False


def main():
    """Record VCR cassettes."""
    print("🎬 VCR CASSETTE RECORDING SCRIPT")
    print("=" * 40)

    if not check_credentials():
        print("❌ Missing credentials!")
        print("Please set up your .env file with:")
        print("   UZH_USERNAME=your_username")
        print("   UZH_PASSWORD=your_password")
        print("   UZH_TOTP_SECRET=your_totp_secret")
        return 1

    print("✅ Credentials found")
    print("🔄 Recording real HTTP interactions...")
    print()

    # Record cassettes by running live tests
    cmd = [
        "uv",
        "run",
        "pytest",
        "tests/test_amain_refactored.py",
        "-m",
        "live",
        "-v",
        "-s",
    ]

    try:
        subprocess.run(cmd, check=True)

        print()
        print("🎉 Recording completed!")
        print("📁 Cassettes saved in tests/cassettes/")

        # List created cassettes
        cassette_dir = Path("tests/cassettes")
        if cassette_dir.exists():
            cassettes = list(cassette_dir.glob("*.yaml"))
            if cassettes:
                print("📼 Created cassettes:")
                for cassette in cassettes:
                    print(f"   - {cassette.name}")
            else:
                print("⚠️  No cassettes found")

        print()
        print("🧪 Now you can run replay tests:")
        print("   uv run pytest tests/test_amain_refactored.py -v")

        return 0

    except subprocess.CalledProcessError as e:
        print(f"❌ Recording failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
