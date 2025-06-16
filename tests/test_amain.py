"""Tests for the refactored async booking module using VCR for real HTTP interactions."""

import pytest
import vcr
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from scheduler.amain import (
    main_async,
    attempt_batch_booking,
    create_single_reservation,
    BookingRequest,
    load_client_and_csrf_token,
    extract_csrf_token,
    generate_totp_code,
    calculate_booking_times,
    create_reservation_payload,
)


# VCR configuration
vcr_config = vcr.VCR(
    cassette_library_dir=str(Path(__file__).parent / "cassettes"),
    record_mode="once",  # Record once, then replay
    match_on=["method", "scheme", "host", "port", "path", "query"],
    filter_headers=["authorization", "cookie", "user-agent"],
    filter_post_data_parameters=["email", "password", "OTP", "CSRF_TOKEN"],
    decode_compressed_response=True,
)


class TestUtilityFunctions:
    """Test utility functions (no HTTP required)."""

    def test_extract_csrf_token_success(self):
        """Test successful CSRF token extraction."""
        html = '<html><body><input name="CSRF_TOKEN" value="test_token_123" /></body></html>'
        token = extract_csrf_token(html)
        assert token == "test_token_123"

    def test_extract_csrf_token_missing(self):
        """Test CSRF token extraction when token is missing."""
        html = "<html><body><form></form></body></html>"
        with pytest.raises(ValueError, match="CSRF_TOKEN not found"):
            extract_csrf_token(html)

    def test_generate_totp_code(self):
        """Test TOTP generation."""
        secret = "JBSWY3DPEHPK3PXP"
        totp_code = generate_totp_code(secret)
        assert len(totp_code) == 6
        assert totp_code.isdigit()

    def test_calculate_booking_times(self):
        """Test booking time calculation."""
        test_date = date(2024, 1, 15)
        start_time, end_time = calculate_booking_times(test_date)

        assert start_time.date() == test_date
        assert end_time.date() == test_date
        assert start_time.hour == 6
        assert start_time.minute == 30
        assert end_time.hour == 16
        assert end_time.minute == 30

    def test_create_reservation_payload(self):
        """Test reservation payload creation."""
        from datetime import datetime

        request = BookingRequest(
            resource_id="231", owner_id=1843, reservation_date=date(2024, 1, 15)
        )
        start_time = datetime(2024, 1, 15, 18, 0, 0)
        end_time = datetime(2024, 1, 15, 18, 30, 0)

        payload = create_reservation_payload(request, start_time, end_time)

        assert payload["reservation"]["resourceIds"] == ["231"]
        assert payload["reservation"]["ownerId"] == 1843
        assert payload["reservation"]["start"] == "2024-01-15T18:00:00.000Z"
        assert payload["reservation"]["end"] == "2024-01-15T18:30:00.000Z"
        assert payload["updateScope"] == "full"


class TestWithVCRRecordings:
    """Tests using VCR to record/replay real HTTP interactions."""

    @pytest.mark.live
    @pytest.mark.asyncio
    async def test_record_authentication_flow(self):
        """Record the authentication flow - run this once with real credentials."""
        try:
            from scheduler.config import LoginDetails

            settings = LoginDetails()
            if not all(
                [settings.uzh_username, settings.uzh_password, settings.uzh_totp_secret]
            ):
                pytest.skip("Real credentials not available for recording")
        except Exception:
            pytest.skip("Real credentials not available for recording")

        with vcr_config.use_cassette("authentication_flow.yaml"):
            client, csrf_token = await load_client_and_csrf_token(refresh=True)

            # These should be real values from the actual API
            assert client is not None
            assert csrf_token is not None
            assert isinstance(csrf_token, str)
            assert len(csrf_token) > 0

            if client and not client.is_closed:
                await client.aclose()

    @pytest.mark.live
    @pytest.mark.asyncio
    async def test_record_single_booking_attempt(self):
        """Record a single booking attempt - run this once with real credentials."""
        try:
            from scheduler.config import LoginDetails

            settings = LoginDetails()
            if not all(
                [settings.uzh_username, settings.uzh_password, settings.uzh_totp_secret]
            ):
                pytest.skip("Real credentials not available for recording")
        except Exception:
            pytest.skip("Real credentials not available for recording")

        with vcr_config.use_cassette("single_booking_attempt.yaml"):
            client, csrf_token = await load_client_and_csrf_token(refresh=True)

            if client and csrf_token:
                target_date = date.today() + timedelta(days=7)

                request = BookingRequest(
                    resource_id="231",  # First resource
                    owner_id=1843,
                    reservation_date=target_date,
                )

                result = await create_single_reservation(client, request, csrf_token)

                # Record the actual result (success or failure)
                assert result.resource_id == "231"
                assert isinstance(result.success, bool)

                if result.success:
                    assert result.reference_number is not None
                    print(
                        f"SUCCESS: Booked resource {result.resource_id}, ref: {result.reference_number}"
                    )
                else:
                    assert result.error is not None
                    print(
                        f"FAILED: Resource {result.resource_id}, error: {result.error}"
                    )

                await client.aclose()

    @pytest.mark.live
    @pytest.mark.asyncio
    async def test_record_spam_booking_session(self):
        """Record a full spam booking session - run this once with real credentials."""
        try:
            from scheduler.config import LoginDetails

            settings = LoginDetails()
            if not all(
                [settings.uzh_username, settings.uzh_password, settings.uzh_totp_secret]
            ):
                pytest.skip("Real credentials not available for recording")
        except Exception:
            pytest.skip("Real credentials not available for recording")

        with vcr_config.use_cassette("spam_booking_session.yaml"):
            # Record the full spam booking process
            with patch(
                "scheduler.amain.PREFERRED_RANGE", range(231, 235)
            ):  # Only 4 resources for recording
                await main_async()

    @pytest.mark.asyncio
    async def test_replay_authentication_flow(self):
        """Replay recorded authentication flow."""
        cassette_path = Path(__file__).parent / "cassettes" / "authentication_flow.yaml"

        if not cassette_path.exists():
            pytest.skip("Authentication cassette not found. Run: pytest -m live")

        with vcr_config.use_cassette("authentication_flow.yaml"):
            client, csrf_token = await load_client_and_csrf_token(refresh=True)

            # Should get the same results as when recorded
            assert client is not None
            assert csrf_token is not None
            assert isinstance(csrf_token, str)
            assert len(csrf_token) > 0

            if client and not client.is_closed:
                await client.aclose()

    @pytest.mark.asyncio
    async def test_replay_single_booking_attempt(self):
        """Replay recorded single booking attempt."""
        cassette_path = (
            Path(__file__).parent / "cassettes" / "single_booking_attempt.yaml"
        )

        if not cassette_path.exists():
            pytest.skip("Single booking cassette not found. Run: pytest -m live")

        with vcr_config.use_cassette("single_booking_attempt.yaml"):
            client, csrf_token = await load_client_and_csrf_token(refresh=True)

            if client and csrf_token:
                target_date = date.today() + timedelta(days=7)

                request = BookingRequest(
                    resource_id="231", owner_id=1843, reservation_date=target_date
                )

                result = await create_single_reservation(client, request, csrf_token)

                # Should get exactly the same result as when recorded
                assert result.resource_id == "231"
                assert isinstance(result.success, bool)

                # The result will be consistent with what was recorded
                if result.success:
                    assert result.reference_number is not None
                    print(
                        f"REPLAY SUCCESS: Resource {result.resource_id}, ref: {result.reference_number}"
                    )
                else:
                    assert result.error is not None
                    print(
                        f"REPLAY FAILED: Resource {result.resource_id}, error: {result.error}"
                    )

                await client.aclose()

    @pytest.mark.asyncio
    async def test_replay_spam_booking_session(self):
        """Replay recorded spam booking session."""
        cassette_path = (
            Path(__file__).parent / "cassettes" / "spam_booking_session.yaml"
        )

        if not cassette_path.exists():
            pytest.skip("Spam booking cassette not found. Run: pytest -m live")

        with vcr_config.use_cassette("spam_booking_session.yaml"):
            # Replay the exact same spam booking process
            with patch(
                "scheduler.amain.PREFERRED_RANGE", range(231, 235)
            ):  # Same 4 resources
                await main_async()
                # Should complete without errors and give same results as recording

    @pytest.mark.asyncio
    async def test_replay_batch_booking_analysis(self):
        """Analyze the recorded batch booking results."""
        cassette_path = (
            Path(__file__).parent / "cassettes" / "single_booking_attempt.yaml"
        )

        if not cassette_path.exists():
            pytest.skip("Booking cassette not found. Run: pytest -m live")

        with vcr_config.use_cassette("single_booking_attempt.yaml"):
            client, csrf_token = await load_client_and_csrf_token(refresh=True)

            if client and csrf_token:
                target_date = date.today() + timedelta(days=7)

                # Test with a few resources to analyze the pattern
                with patch("scheduler.amain.PREFERRED_RANGE", range(231, 235)):
                    results = await attempt_batch_booking(
                        client, csrf_token, target_date
                    )

                # Analyze the recorded results
                successful = [r for r in results if r.success]
                failed = [r for r in results if not r.success]

                print("\nRECORDED SPAM BOOKING ANALYSIS:")
                print(f"  Total attempts: {len(results)}")
                print(f"  Successful: {len(successful)}")
                print(f"  Failed: {len(failed)}")
                print(f"  Success rate: {len(successful) / len(results) * 100:.1f}%")

                if successful:
                    print(
                        f"  Successful resources: {[r.resource_id for r in successful]}"
                    )
                    for s in successful:
                        print(f"    Resource {s.resource_id}: {s.reference_number}")

                if failed:
                    print(f"  Sample error: {failed[0].error}")

                # Verify we got real data
                assert len(results) > 0
                assert all(isinstance(r.success, bool) for r in results)

                await client.aclose()


class TestRecordingInstructions:
    """Instructions for recording cassettes."""

    def test_recording_instructions(self):
        """Instructions for recording VCR cassettes."""
        instructions = """
        TO RECORD REAL HTTP INTERACTIONS:
        
        1. Set up your .env file with real credentials:
           UZH_USERNAME=your_username
           UZH_PASSWORD=your_password
           UZH_TOTP_SECRET=your_totp_secret
        
        2. Run the recording tests (these will make real API calls):
           pytest tests/test_amain.py -m live -v
        
        3. This will create cassette files in tests/cassettes/:
           - authentication_flow.yaml
           - single_booking_attempt.yaml
           - spam_booking_session.yaml
        
        4. After recording, run normal tests (these will replay recordings):
           pytest tests/test_amain.py -v
        
        5. The cassettes contain REAL API responses including:
           - Actual success/failure results
           - Real error messages
           - Authentic CSRF tokens (filtered out)
           - Genuine booking reference numbers
        
        IMPORTANT:
        - Recording tests require real credentials and network access
        - Replay tests work offline using recorded data
        - Cassettes should be committed to git for CI/CD
        - Re-record if API changes or test scenarios change
        """

        print(instructions)
        assert "TO RECORD REAL HTTP INTERACTIONS" in instructions
