"""
Refactored async booking module with improved structure and readability.

This module provides a cleaner, more maintainable version of the booking system
while maintaining the same functionality as the original amain.py.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, AsyncGenerator, Protocol

import httpx
import pyotp
from bs4 import BeautifulSoup

from scheduler.config import (
    BookingDetails,
    LoginDetails,
    BookingConstants,
    persistent_cache,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Data Classes and Protocols ---


@dataclass
class BookingRequest:
    """Structured booking request data."""

    resource_id: str
    owner_id: int
    reservation_date: date | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None


@dataclass
class BookingResult:
    """Structured booking result."""

    resource_id: str
    success: bool
    error: str | None = None
    reference_number: str | None = None


class AuthenticatedClient(Protocol):
    """Protocol for authenticated HTTP clients."""

    async def post(self, url: str, **kwargs) -> httpx.Response: ...
    async def get(self, url: str, **kwargs) -> httpx.Response: ...
    async def aclose(self) -> None: ...

    @property
    def cookies(self) -> Any: ...

    @property
    def headers(self) -> Any: ...

    @property
    def is_closed(self) -> bool: ...


# --- Custom Exceptions ---


class SessionExpiredError(Exception):
    """Custom exception to indicate a session has expired or CSRF is invalid."""

    pass


class AuthenticationError(Exception):
    """Custom exception for authentication failures."""

    pass


class BookingError(Exception):
    """Custom exception for booking-related errors."""

    pass


# --- Configuration Setup ---

booking_details = BookingDetails()
settings = LoginDetails()

# URL Configuration
BASE_URL = booking_details.base_url
LOGIN_PAGE_URL = booking_details.login_page_url
LOGIN_ACTION_URL = booking_details.login_action_url
TFA_VALIDATE_URL = booking_details.tfa_validate_url

# Booking Configuration
OWNER_ID = booking_details.owner_id
PREFERRED_RANGE = range(
    booking_details.preferred_range_start, booking_details.preferred_range_end
)
PREFERRED_START_TIME_HOUR = booking_details.preferred_start_time_hour
PREFERRED_START_TIME_MINUTE = booking_details.preferred_start_time_minute
PREFERRED_END_TIME_HOUR = booking_details.preferred_end_time_hour
PREFERRED_END_TIME_MINUTE = booking_details.preferred_end_time_minute
STANDARD_ATTRIBUTE_VALUES = booking_details.standard_attribute_values

# Credentials
USERNAME = settings.uzh_username
PASSWORD = settings.uzh_password
TOTP_SECRET = settings.uzh_totp_secret


# --- Utility Functions ---


def extract_csrf_token(html_content: str) -> str:
    """
    Extract CSRF token from HTML content.

    Args:
        html_content: HTML content containing the CSRF token

    Returns:
        The CSRF token value

    Raises:
        ValueError: If CSRF token is not found or empty
    """
    soup = BeautifulSoup(html_content, "html.parser")
    token_input = soup.find("input", {"name": "CSRF_TOKEN"})

    if not token_input or not token_input.get("value"):
        raise ValueError("CSRF_TOKEN not found in the provided HTML content.")

    return token_input["value"]


def generate_totp_code(secret: str) -> str:
    """
    Generate TOTP code from secret.

    Args:
        secret: TOTP secret key

    Returns:
        6-digit TOTP code
    """
    totp = pyotp.TOTP(secret)
    return totp.now()


def create_reservation_payload(
    request: BookingRequest, start_time: datetime, end_time: datetime
) -> dict[str, Any]:
    """
    Create reservation payload for API request.

    Args:
        request: Booking request details
        start_time: Reservation start time
        end_time: Reservation end time

    Returns:
        Complete reservation payload
    """
    start_iso_str = start_time.isoformat(timespec="milliseconds") + "Z"
    end_iso_str = end_time.isoformat(timespec="milliseconds") + "Z"
    terms_accepted_date_str = datetime.now().isoformat(timespec="milliseconds") + "Z"

    reservation_details = {
        "referenceNumber": None,
        "ownerId": request.owner_id,
        "resourceIds": [request.resource_id],
        "accessories": [],
        "title": "",
        "description": "",
        "start": start_iso_str,
        "end": end_iso_str,
        "recurrence": {
            "type": "none",
            "interval": 1,
            "weekdays": None,
            "monthlyType": None,
            "weekOfMonth": None,
            "terminationDate": None,
            "repeatDates": [],
        },
        "startReminder": None,
        "endReminder": None,
        "inviteeIds": [],
        "coOwnerIds": [],
        "participantIds": [],
        "guestEmails": [],
        "participantEmails": [],
        "allowSelfJoin": False,
        "attachments": [],
        "requiresApproval": False,
        "checkinDate": None,
        "checkoutDate": None,
        "termsAcceptedDate": terms_accepted_date_str,
        "attributeValues": STANDARD_ATTRIBUTE_VALUES,
        "meetingLink": None,
        "displayColor": None,
    }

    return {
        "reservation": reservation_details,
        "retryParameters": [],
        "updateScope": "full",
    }


def calculate_booking_times(reservation_date: date) -> tuple[datetime, datetime]:
    """
    Calculate start and end times for a booking on the given date.

    Args:
        reservation_date: Date for the reservation

    Returns:
        Tuple of (start_time, end_time)
    """
    start_time = datetime(
        reservation_date.year,
        reservation_date.month,
        reservation_date.day,
        PREFERRED_START_TIME_HOUR,
        PREFERRED_START_TIME_MINUTE,
    )
    end_time = datetime(
        reservation_date.year,
        reservation_date.month,
        reservation_date.day,
        PREFERRED_END_TIME_HOUR,
        PREFERRED_END_TIME_MINUTE,
    )
    return start_time, end_time


# --- Authentication Functions ---


async def perform_initial_login(client: httpx.AsyncClient) -> httpx.Response:
    """
    Perform initial username/password login.

    Args:
        client: HTTP client to use for requests

    Returns:
        Response from login attempt

    Raises:
        httpx.RequestError: If request fails
    """
    logger.info("Accessing login page...")
    initial_response = await client.get(
        LOGIN_PAGE_URL, timeout=BookingConstants.DEFAULT_TIMEOUT
    )
    initial_response.raise_for_status()

    logger.info("Submitting username and password...")
    login_payload = {
        "email": USERNAME,
        "password": PASSWORD,
        "captcha": "",
        "login": "submit",
        "resume": "",
        "language": "en_us",
    }

    login_headers = {
        "Referer": LOGIN_PAGE_URL,
        "Origin": BASE_URL.rstrip("/"),
    }

    login_response = await client.post(
        LOGIN_ACTION_URL,
        data=login_payload,
        headers=login_headers,
        follow_redirects=True,
        timeout=BookingConstants.DEFAULT_TIMEOUT,
    )
    login_response.raise_for_status()

    logger.info(
        f"Login submission to {login_response.url}, status: {login_response.status_code}"
    )
    return login_response


async def handle_2fa_if_required(
    client: httpx.AsyncClient, login_response: httpx.Response
) -> bool:
    """
    Handle 2FA if required by the login response.

    Args:
        client: HTTP client to use for requests
        login_response: Response from initial login

    Returns:
        True if 2FA was handled successfully or not required

    Raises:
        ValueError: If CSRF token cannot be extracted
        httpx.RequestError: If 2FA request fails
    """
    if "passcode" not in login_response.text.lower():
        logger.info("2FA not required")
        return True

    logger.info("2FA step detected")
    csrf_token_2fa = extract_csrf_token(login_response.text)
    totp_code = generate_totp_code(TOTP_SECRET)

    tfa_payload = {
        "CSRF_TOKEN": csrf_token_2fa,
        "OTP": totp_code,
    }

    tfa_headers = {
        "Referer": str(login_response.url),
        "Origin": BASE_URL.rstrip("/"),
    }

    logger.info("Submitting TOTP code...")
    tfa_response = await client.post(
        TFA_VALIDATE_URL,
        data=tfa_payload,
        headers=tfa_headers,
        follow_redirects=True,
        timeout=BookingConstants.DEFAULT_TIMEOUT,
    )
    tfa_response.raise_for_status()

    logger.info(
        f"2FA submission to {tfa_response.url}, status: {tfa_response.status_code}"
    )
    return True


def verify_login_success(client: httpx.AsyncClient) -> bool:
    """
    Verify that login was successful by checking for login token.

    Args:
        client: HTTP client to check

    Returns:
        True if login was successful
    """
    if "login_token" in client.cookies:
        logger.info("Login successful!")
        return True
    else:
        logger.warning("Login may have failed - login_token not found in cookies")
        return False


async def authenticate_client(client: httpx.AsyncClient) -> bool:
    """
    Perform complete authentication flow.

    Args:
        client: HTTP client to authenticate

    Returns:
        True if authentication was successful

    Raises:
        AuthenticationError: If authentication fails
    """
    try:
        login_response = await perform_initial_login(client)
        await handle_2fa_if_required(client, login_response)

        if not verify_login_success(client):
            raise AuthenticationError("Login verification failed")

        return True

    except (httpx.RequestError, ValueError) as e:
        logger.exception(f"Authentication failed: {e}")
        raise AuthenticationError(f"Authentication failed: {e}") from e


async def get_csrf_token_from_schedule_page(client: httpx.AsyncClient) -> str:
    """
    Get CSRF token from the schedule page.

    Args:
        client: Authenticated HTTP client

    Returns:
        CSRF token for booking operations

    Raises:
        ValueError: If CSRF token cannot be extracted
        httpx.RequestError: If request fails
    """
    logger.info("Fetching CSRF token from schedule page...")

    schedule_headers = {
        "Accept": BookingConstants.ACCEPT,
    }

    response = await client.get(
        BASE_URL,
        headers=schedule_headers,
        timeout=BookingConstants.DEFAULT_TIMEOUT,
        follow_redirects=True,
    )
    response.raise_for_status()

    csrf_token = extract_csrf_token(response.text)
    logger.info(f"Fetched CSRF token: {csrf_token[:10]}...")
    return csrf_token


# --- Session Management ---


@asynccontextmanager
async def authenticated_session(
    refresh: bool = False,
) -> AsyncGenerator[tuple[httpx.AsyncClient, str], None]:
    """
    Context manager for authenticated HTTP sessions.

    Args:
        refresh: Whether to force refresh the session

    Yields:
        Tuple of (authenticated_client, csrf_token)

    Raises:
        AuthenticationError: If authentication fails
    """
    client = None
    try:
        client, csrf_token = await load_client_and_csrf_token(refresh=refresh)
        if not client or not csrf_token:
            raise AuthenticationError("Failed to establish authenticated session")
        yield client, csrf_token
    finally:
        if client and not client.is_closed:
            await client.aclose()


def get_cache_keys() -> tuple[str, str, str]:
    """Get cache keys for session data."""
    return "client_headers", "csrf_token", "client_cookies_jar"


def cache_session_data(
    headers: dict[str, str], cookies: dict[str, str], csrf_token: str
) -> None:
    """
    Cache session data for reuse.

    Args:
        headers: HTTP headers to cache
        cookies: Cookies to cache
        csrf_token: CSRF token to cache
    """
    cache_key_headers, cache_key_csrf, cache_key_cookies = get_cache_keys()
    expiry_seconds = BookingConstants.CACHE_EXPIRY_HOURS * 60 * 60

    persistent_cache.set(cache_key_headers, headers, expire=expiry_seconds)
    persistent_cache.set(cache_key_cookies, cookies, expire=expiry_seconds)
    persistent_cache.set(cache_key_csrf, csrf_token, expire=expiry_seconds)

    logger.info("Successfully cached session data")


def load_cached_session_data() -> tuple[
    dict[str, str] | None, dict[str, str] | None, str | None
]:
    """
    Load session data from cache.

    Returns:
        Tuple of (headers, cookies, csrf_token) or (None, None, None) if cache miss
    """
    cache_key_headers, cache_key_csrf, cache_key_cookies = get_cache_keys()

    cached_headers = persistent_cache.get(cache_key_headers)
    cached_csrf = persistent_cache.get(cache_key_csrf)
    cached_cookies = persistent_cache.get(cache_key_cookies)

    if not all([cached_headers, cached_csrf, cached_cookies]):
        return None, None, None

    # Validate cache data types
    if not (
        isinstance(cached_headers, dict)
        and isinstance(cached_csrf, str)
        and isinstance(cached_cookies, dict)
    ):
        logger.warning("Cached data type mismatch")
        return None, None, None

    # Validate cookie values are strings
    for name, value in cached_cookies.items():
        if not isinstance(value, str):
            logger.warning(f"Invalid cookie value type for '{name}'")
            return None, None, None

    return cached_headers, cached_cookies, cached_csrf


def create_http_client() -> httpx.AsyncClient:
    """
    Create HTTP client with standard headers.

    Returns:
        Configured HTTP client
    """
    client = httpx.AsyncClient()
    client.headers.update(
        {
            "User-Agent": BookingConstants.USER_AGENT,
            "Accept-Language": BookingConstants.ACCEPT_LANGUAGE,
            "Accept-Encoding": BookingConstants.ACCEPT_ENCODING,
            "Connection": BookingConstants.CONNECTION,
            "Accept": BookingConstants.ACCEPT,
        }
    )
    return client


async def create_fresh_session() -> tuple[httpx.AsyncClient, str]:
    """
    Create a fresh authenticated session.

    Returns:
        Tuple of (authenticated_client, csrf_token)

    Raises:
        AuthenticationError: If authentication fails
    """
    client = create_http_client()

    try:
        await authenticate_client(client)
        csrf_token = await get_csrf_token_from_schedule_page(client)

        # Cache the session data
        cookies_to_cache = {
            name: value
            for name, value in client.cookies.items()
            if isinstance(value, str)
        }
        headers_to_cache = dict(client.headers)
        cache_session_data(headers_to_cache, cookies_to_cache, csrf_token)

        return client, csrf_token

    except Exception as e:
        if not client.is_closed:
            await client.aclose()
        raise AuthenticationError(f"Failed to create fresh session: {e}") from e


async def load_client_and_csrf_token(
    *, refresh: bool = False
) -> tuple[httpx.AsyncClient | None, str | None]:
    """
    Load authenticated client and CSRF token, using cache when possible.

    Args:
        refresh: Whether to force refresh the session

    Returns:
        Tuple of (client, csrf_token) or (None, None) if failed
    """
    if not refresh:
        logger.debug("Attempting to load client data from cache")
        cached_headers, cached_cookies, cached_csrf = load_cached_session_data()

        if all([cached_headers, cached_cookies, cached_csrf]):
            try:
                client = create_http_client()
                client.headers.update(cached_headers)
                client.cookies.update(cached_cookies)
                logger.info("Using cached client and CSRF token")
                return client, cached_csrf
            except Exception as e:
                logger.warning(f"Failed to recreate client from cache: {e}")
        else:
            logger.info("Cache miss - creating fresh session")
    else:
        logger.info("Explicitly refreshing session")

    try:
        return await create_fresh_session()
    except AuthenticationError as e:
        logger.error(f"Failed to create session: {e}")
        return None, None


# --- Booking Functions ---


async def create_single_reservation(
    client: httpx.AsyncClient, request: BookingRequest, csrf_token: str
) -> BookingResult:
    """
    Create a single reservation.

    Args:
        client: Authenticated HTTP client
        request: Booking request details
        csrf_token: CSRF token for the request

    Returns:
        Booking result with success status and details
    """
    try:
        # Calculate booking times
        if request.start_time and request.end_time:
            start_time, end_time = request.start_time, request.end_time
        elif request.reservation_date:
            start_time, end_time = calculate_booking_times(request.reservation_date)
        else:
            raise ValueError(
                "Either reservation_date or start_time/end_time must be provided"
            )

        # Create API payload
        api_payload = create_reservation_payload(request, start_time, end_time)

        # Prepare form data
        booking_form_parts = {
            "request": (None, json.dumps(api_payload), "application/json"),
            "CSRF_TOKEN": (None, csrf_token),
            "BROWSER_TIMEZONE": (None, BookingConstants.TIMEZONE),
        }

        booking_headers = {
            "X-Csrf-Token": csrf_token,
        }

        # Make the request
        booking_url = BASE_URL + "api/reservation.php?action=create"
        response = await client.post(
            booking_url,
            files=booking_form_parts,
            headers=booking_headers,
            timeout=BookingConstants.DEFAULT_TIMEOUT,
        )
        response.raise_for_status()

        # Process response
        try:
            resp_json = response.json()
            logger.debug(f"Reservation response: {json.dumps(resp_json, indent=2)}")

            if resp_json.get("success") and resp_json.get("data", {}).get("success"):
                reference_number = resp_json.get("data", {}).get("referenceNumber")
                return BookingResult(
                    resource_id=request.resource_id,
                    success=True,
                    reference_number=reference_number,
                )

            # Extract error message
            error_msg = None
            if errors := resp_json.get("data", {}).get("errors"):
                error_msg = str(errors)
            elif message := resp_json.get("message"):
                error_msg = message

            return BookingResult(
                resource_id=request.resource_id, success=False, error=error_msg
            )

        except json.JSONDecodeError as e:
            logger.exception(f"Error parsing reservation response: {e}")
            return BookingResult(
                resource_id=request.resource_id,
                success=False,
                error="Invalid JSON response",
            )

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            logger.error("401 Unauthorized - session expired")
            raise SessionExpiredError("Session or CSRF token expired") from e

        error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        return BookingResult(
            resource_id=request.resource_id, success=False, error=error_msg
        )

    except Exception as e:
        logger.exception(f"Unexpected error during reservation: {e}")
        return BookingResult(
            resource_id=request.resource_id, success=False, error=str(e)
        )


async def attempt_batch_booking(
    client: httpx.AsyncClient, csrf_token: str, target_date: date | None = None
) -> list[BookingResult]:
    """
    Attempt to book multiple resources concurrently (SPAM STRATEGY).

    This function implements the "spam" approach - trying ALL resources
    simultaneously to maximize speed and success probability in competitive
    booking scenarios where others are also trying to book at the same time.

    Strategy rationale:
    - Speed is critical (first-come, first-served)
    - Concurrent requests are ~30x faster than sequential
    - High failure rate is expected and normal
    - Better to try everything than miss opportunities

    Args:
        client: Authenticated HTTP client
        csrf_token: CSRF token for requests
        target_date: Date to book (defaults to one week from today)

    Returns:
        List of booking results (expect 95%+ failure rate - this is normal!)
    """
    if target_date is None:
        target_date = date.today() + timedelta(days=7)

    resource_count = len(PREFERRED_RANGE)
    logger.info(
        f"🚀 SPAM BOOKING: Attempting {resource_count} resources concurrently for {target_date}"
    )
    logger.info(f"📍 Resource range: {min(PREFERRED_RANGE)}-{max(PREFERRED_RANGE)}")
    logger.info("⚡ Strategy: Concurrent spam for maximum speed")

    # Create booking requests for ALL resources in range
    requests = [
        BookingRequest(
            resource_id=str(resource_id),
            owner_id=OWNER_ID,
            reservation_date=target_date,
        )
        for resource_id in PREFERRED_RANGE
    ]

    # Create tasks for concurrent execution - this is the "spam"
    # All requests fire simultaneously for maximum speed
    tasks = [
        create_single_reservation(client, request, csrf_token) for request in requests
    ]

    # Execute ALL bookings concurrently - the core of the spam strategy
    logger.info(f"⚡ Firing {len(tasks)} concurrent booking requests...")
    start_time = asyncio.get_event_loop().time()

    results = await asyncio.gather(*tasks, return_exceptions=True)

    end_time = asyncio.get_event_loop().time()
    duration = end_time - start_time

    logger.info(
        f"⏱️  Spam booking completed in {duration:.2f}s ({duration / len(tasks):.3f}s avg per request)"
    )

    # Process results and handle exceptions
    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, SessionExpiredError):
            logger.error(f"Session expired for resource {requests[i].resource_id}")
            raise result  # Re-raise to trigger retry logic
        elif isinstance(result, Exception):
            logger.warning(
                f"Unexpected exception for resource {requests[i].resource_id}: {result}"
            )
            processed_results.append(
                BookingResult(
                    resource_id=requests[i].resource_id,
                    success=False,
                    error=str(result),
                )
            )
        else:
            processed_results.append(result)

    return processed_results


def log_booking_summary(results: list[BookingResult]) -> int:
    """
    Log summary of booking results.

    Args:
        results: List of booking results

    Returns:
        Number of successful bookings
    """
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    logger.info("Booking Summary:")
    logger.info(f"  Successful: {len(successful)}")
    logger.info(f"  Failed: {len(failed)}")

    if successful:
        success_ids = [r.resource_id for r in successful]
        logger.info(f"  Successful resources: {success_ids}")

    if failed:
        for result in failed:
            logger.warning(f"  Failed resource {result.resource_id}: {result.error}")

    return len(successful)


# --- Main Booking Function ---


async def main_async() -> None:
    """
    Main async booking function with retry logic.

    This function orchestrates the entire booking process including:
    - Authentication with retry on session expiry
    - Batch booking of multiple resources
    - Error handling and logging
    """
    max_retries = 1

    for attempt in range(max_retries + 1):
        try:
            logger.info(f"Booking attempt {attempt + 1}/{max_retries + 1}")

            async with authenticated_session(refresh=attempt > 0) as (
                client,
                csrf_token,
            ):
                results = await attempt_batch_booking(client, csrf_token)
                success_count = log_booking_summary(results)

                if success_count > 0:
                    logger.info("✅ Booking completed successfully!")
                    return

                logger.info("No successful bookings in this attempt")

                # Check if we should retry on general failure
                if (
                    hasattr(booking_details, "retry_on_fail")
                    and booking_details.retry_on_fail
                ):
                    if attempt < max_retries:
                        delay = getattr(booking_details, "retry_delay_seconds", 30)
                        logger.info(f"Waiting {delay}s before retry...")
                        time.sleep(delay)
                        continue

                break  # No retry needed

        except SessionExpiredError:
            if attempt < max_retries:
                logger.info(f"Session expired. Retrying ({attempt + 1}/{max_retries})")
                continue
            logger.error("Max retries reached after session expiry")
            break

        except Exception as e:
            logger.exception(f"Unexpected error in booking attempt {attempt + 1}: {e}")
            if attempt < max_retries:
                logger.info("Retrying due to unexpected error...")
                continue
            break

    logger.info("Booking process completed")


# --- Backward Compatibility Functions ---

# Keep the original function names for backward compatibility
get_csrf_token = extract_csrf_token
generate_totp = generate_totp_code


async def create_reservation(
    client: httpx.AsyncClient,
    owner_id: int,
    resource_id: str,
    csrf_token: str,
    reservation_date: date | None = None,
    start_time: dt.datetime | None = None,
    end_time: dt.datetime | None = None,
) -> bool:
    """
    Backward compatibility wrapper for create_single_reservation.

    This function maintains the same interface as the original create_reservation
    function to ensure existing tests continue to work.
    """
    request = BookingRequest(
        resource_id=resource_id,
        owner_id=owner_id,
        reservation_date=reservation_date,
        start_time=start_time,
        end_time=end_time,
    )

    result = await create_single_reservation(client, request, csrf_token)
    return result.success


async def fetch_schedule_reservations(
    client: httpx.AsyncClient,
    BASE_URL: str,
    schedule_id: int,
    start_date: date,
    end_date: date,
    csrf_token: str,
) -> dict[str, Any] | None:
    """
    Fetch schedule reservations (unchanged from original).

    This function is kept as-is for backward compatibility.
    """
    FETCH_URL = BASE_URL.rstrip("/") + "/schedule.php?dr=reservations"
    REFERER_URL = BASE_URL.rstrip("/") + f"/schedule.php?scheduleid={schedule_id}"

    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    headers = {
        "Accept": "*/*",
        "Origin": BASE_URL.split("/ub/Web/")[0],
        "Referer": REFERER_URL,
        "X-Requested-With": "XMLHttpRequest",
    }

    form_data_parts = {
        "beginDate": (None, start_date_str),
        "endDate": (None, end_date_str),
        "scheduleId": (None, str(schedule_id)),
        "LAST_REFRESH": (None, ""),
        "MIN_CAPACITY": (None, ""),
        "RESOURCE_TYPE_ID": (None, ""),
        "userId": (None, ""),
        "USER_LEVEL": (None, ""),
        "CSRF_TOKEN": (None, csrf_token),
    }

    logger.info(
        f"Fetching reservations for schedule {schedule_id} from {start_date_str} to {end_date_str}"
    )

    try:
        response = await client.post(
            FETCH_URL,
            headers=headers,
            files=form_data_parts,
            timeout=BookingConstants.DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    except httpx.HTTPStatusError as e:
        logger.exception(f"HTTP error during reservation fetch: {e}")
        return None
    except httpx.RequestError as e:
        logger.exception(f"Request error during reservation fetch: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.exception(f"Error decoding JSON response: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error during reservation fetch: {e}")
        return None


# --- Entry Points ---


def main() -> None:
    """Synchronous entry point."""
    asyncio.run(main_async())


def reload_csrf_token() -> None:
    """Reload CSRF token by refreshing session."""
    asyncio.run(load_client_and_csrf_token(refresh=True))


if __name__ == "__main__":
    main()
