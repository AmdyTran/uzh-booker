from __future__ import annotations

import datetime as dt
import json
import logging
from datetime import date, datetime, timedelta
import time
from typing import Any
import pyotp
import httpx
import asyncio
from bs4 import BeautifulSoup
from scheduler.config import LoginDetails, BookingDetails, persistent_cache


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Custom Exception for session/auth failures
class SessionExpiredError(Exception):
    """Custom exception to indicate a session has expired or CSRF is invalid."""

    pass


booking_details = BookingDetails()
# --- Configuration ---
BASE_URL = booking_details.base_url
LOGIN_PAGE_URL = booking_details.login_page_url
LOGIN_ACTION_URL = booking_details.login_action_url
TFA_VALIDATE_URL = booking_details.tfa_validate_url
OWNER_ID = booking_details.owner_id

PREFERRED_RANGE = range(
    booking_details.preferred_range_start, booking_details.preferred_range_end
)
PREFERRED_START_TIME_HOUR, PREFERRED_START_TIME_MINUTE = (
    booking_details.preferred_start_time_hour,
    booking_details.preferred_start_time_minute,
)
PREFERRED_END_TIME_HOUR, PREFERRED_END_TIME_MINUTE = (
    booking_details.preferred_end_time_hour,
    booking_details.preferred_end_time_minute,
)
STANDARD_ATTRIBUTE_VALUES = booking_details.standard_attribute_values
# Booking details
TARGET_RESOURCE_ID = "33"  # !!! VERIFY THIS !!!
TARGET_START_TIME_STR = "09:00"
# --- Credentials ---
# USE ENVIRONMENT VARIABLES FOR PRODUCTION

settings = LoginDetails()  # type: ignore[call-arg]
USERNAME = settings.uzh_username
PASSWORD = settings.uzh_password
TOTP_SECRET = settings.uzh_totp_secret


def get_csrf_token(text_content: str) -> str:
    soup = BeautifulSoup(text_content, "html.parser")
    token_input = soup.find("input", {"name": "CSRF_TOKEN"})
    if token_input and token_input.get("value"):
        return token_input["value"]
    raise ValueError("CSRF_TOKEN not found in the provided HTML content.")


def generate_totp(secret: str) -> str:
    totp = pyotp.TOTP(secret)
    return totp.now()


async def fetch_schedule_reservations(  # noqa: PLR0913
    client: httpx.AsyncClient,
    BASE_URL: str,
    schedule_id: int,
    start_date: date,
    end_date: date,
    csrf_token: str,
) -> dict[str, Any] | None:
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
    logger.info(f"Target URL: {FETCH_URL}")

    try:
        response = await client.post(
            FETCH_URL,
            headers=headers,
            files=form_data_parts,
            timeout=15,
        )
        response.raise_for_status()

        logger.info(f"Fetch Response Status: {response.status_code}")
        return response.json()

    except httpx.HTTPStatusError as e:
        logger.exception(
            f"Error during reservation fetch request (HTTPStatusError): {e}"
        )
        logger.exception(f"Response status: {e.response.status_code}")
        logger.exception(f"Response content: {e.response.text[:500]}")
        return None
    except httpx.RequestError as e:
        logger.exception(f"Error during reservation fetch request (RequestError): {e}")
        if hasattr(e, "response") and e.response is not None:
            logger.exception(f"Response status: {e.response.status_code}")  # type: ignore
            logger.exception(f"Response content: {e.response.text[:500]}")  # type: ignore
        return None
    except json.JSONDecodeError as e:
        logger.exception(f"Error decoding JSON response: {e}")
        # response might not be defined if httpx.RequestError occurred before response
        # logger.exception(f"Response Text: {response.text}") # Keep this if you want to see non-JSON response
        return None
    except Exception as e:
        logger.exception(f"An unexpected error occurred during reservation fetch: {e}")
        return None


async def login(client: httpx.AsyncClient) -> None:  # noqa: PLR0911, PLR0915,PLR0912
    logger.info("Step 1: Accessing login page to get initial CSRF token and cookies...")
    try:
        r_initial = await client.get(LOGIN_PAGE_URL, timeout=10)
        r_initial.raise_for_status()
        logger.info(f"Initial Cookies: {client.cookies}")
        login_headers = {
            "Referer": LOGIN_PAGE_URL,
            "Origin": BASE_URL.rstrip("/"),
        }

    except httpx.RequestError as e:
        logger.exception(f"Error getting initial page: {e}")
        return
    except ValueError as e:
        logger.exception(f"Error parsing CSRF: {e}")
        logger.exception("HTML content for debugging CSRF:")
        if "r_initial" in locals():
            logger.exception(r_initial.text[:1000])
        return

    logger.info("\nStep 2: Submitting username and password...")
    login_payload = {
        "email": USERNAME,
        "password": PASSWORD,
        "captcha": "",
        "login": "submit",
        "resume": "",
        "language": "en_us",
    }
    try:
        r_login = await client.post(
            LOGIN_ACTION_URL,
            data=login_payload,
            headers=login_headers,
            follow_redirects=True,
            timeout=10,
        )
        r_login.raise_for_status()
        logger.info(f"Login submission to {r_login.url}, status: {r_login.status_code}")
        logger.debug(f"Cookies after login attempt: {client.cookies}")

        if "passcode" in r_login.text.lower():
            logger.info("2FA step detected.")
            try:
                csrf_token_2fa = get_csrf_token(r_login.text)
                logger.debug(f"2FA Page CSRF Token: {csrf_token_2fa}")
            except ValueError as e:
                logger.exception(f"Error parsing CSRF from 2FA page: {e}")
                logger.exception("HTML content for debugging 2FA CSRF:")
                logger.exception(r_login.text[:1500])
                return

            totp_code = generate_totp(TOTP_SECRET)

            tfa_payload = {
                "CSRF_TOKEN": csrf_token_2fa,
                "OTP": totp_code,
            }
            tfa_headers = {
                "Referer": str(r_login.url),  # Ensure Referer is string
                "Origin": BASE_URL.rstrip("/"),
            }

            logger.info("\nStep 3: Submitting TOTP code...")
            r_tfa = await client.post(
                TFA_VALIDATE_URL,
                data=tfa_payload,
                headers=tfa_headers,
                follow_redirects=True,
                timeout=10,
            )
            r_tfa.raise_for_status()
            logger.info(f"2FA submission to {r_tfa.url}, status: {r_tfa.status_code}")
            logger.info(f"Cookies after 2FA attempt: {client.cookies}")

            if "login_token" in client.cookies:
                logger.info("Login successful after 2FA!")
            else:
                logger.exception(
                    "Login failed after 2FA submission (or success indicators not found)."
                )
                logger.exception(f"Response URL: {r_tfa.url}")
                logger.exception(f"Response Text sample: {r_tfa.text[:1000]}")
                return
        else:
            # Check for login success indicators if 2FA was NOT detected/required
            if "login_token" in client.cookies:
                logger.info("Login successful (no 2FA required or already handled)!")
            else:
                logger.warning(
                    f"Login may have failed or 2FA was expected but not triggered. URL: {r_login.url}"
                )
                logger.warning(f"Response text sample: {r_login.text[:1000]}")
                # Consider if this is a failure state that should return

    except httpx.RequestError as e:
        logger.exception(f"Error during login/2FA HTTP request: {e}")
        if hasattr(e, "response") and e.response is not None:
            logger.exception(f"Response status: {e.response.status_code}")  # type: ignore
            logger.exception(f"Response content: {e.response.text[:500]}")  # type: ignore
        return
    except ValueError as e:  # For get_csrf_token
        logger.exception(f"Error parsing CSRF during login/2FA process: {e}")
        return
    except Exception as e:
        logger.exception(f"An unexpected error occurred during login/2FA: {e}")
        return


async def create_reservation(
    client: httpx.AsyncClient,
    owner_id: int,
    resource_id: str,
    csrf_token: str,
    reservation_date: date | None = None,
    start_time: dt.datetime | None = None,
    end_time: dt.datetime | None = None,
) -> bool:
    booking_service_url = BASE_URL + "api/reservation.php?action=create"

    if reservation_date:
        start_time = dt.datetime(
            reservation_date.year,
            reservation_date.month,
            reservation_date.day,
            PREFERRED_START_TIME_HOUR,
            PREFERRED_START_TIME_MINUTE,
        )
        end_time = dt.datetime(
            reservation_date.year,
            reservation_date.month,
            reservation_date.day,
            PREFERRED_END_TIME_HOUR,
            PREFERRED_END_TIME_MINUTE,
        )

    if not start_time or not end_time:
        raise ValueError("start_time and end_time or reservation_date must be provided")

    start_iso_str = start_time.isoformat(timespec="milliseconds") + "Z"
    end_iso_str = end_time.isoformat(timespec="milliseconds") + "Z"
    terms_accepted_date_str = datetime.now().isoformat(timespec="milliseconds") + "Z"
    reservation_details = {
        "referenceNumber": None,
        "ownerId": owner_id,
        "resourceIds": [resource_id],
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

    api_request_payload = {
        "reservation": reservation_details,
        "retryParameters": [],
        "updateScope": "full",
    }

    booking_form_parts = {
        "request": (None, json.dumps(api_request_payload), "application/json"),
        "CSRF_TOKEN": (None, csrf_token),
        "BROWSER_TIMEZONE": (None, "Europe/Zurich"),
    }

    booking_headers = {
        "X-Csrf-Token": csrf_token,
        # httpx will set Content-Type for multipart/form-data automatically
    }

    try:
        r_create = await client.post(
            booking_service_url,
            files=booking_form_parts,
            headers=booking_headers,
            timeout=15,
        )
        r_create.raise_for_status()
        logger.debug(f"Create Response Status: {r_create.status_code}")
        logger.debug(f"Create Response Headers: {r_create.headers}")
        logger.debug(f"Create Response Text: {r_create.text[:500]}")
        try:
            resp_json = r_create.json()
            logger.debug(f"Create Response JSON: {json.dumps(resp_json, indent=2)}")
            if resp_json.get("success"):  # Top-level success
                if resp_json.get("data", {}).get("success"):  # Nested data success
                    return True
            if error := resp_json.get("data", {}).get("errors"):
                logger.warning(f"Reservation creation failed with API errors: {error}")
            elif message := resp_json.get(
                "message"
            ):  # UZH system sometimes uses this for errors
                logger.warning(f"Reservation creation info/error message: {message}")

        except json.JSONDecodeError as e:
            logger.exception(f"Error parsing create reservation response as JSON: {e}")
            return False
    except httpx.HTTPStatusError as e:  # More specific exception
        if e.response.status_code == 401:
            logger.error(
                f"401 Unauthorized during reservation creation. Session or CSRF token likely expired. URL: {e.request.url}"
            )
            raise SessionExpiredError("Session or CSRF token expired") from e
        logger.exception(
            f"HTTP error during reservation creation: {e.response.status_code} - {e.response.text[:500]}"
        )
        return False
    except httpx.RequestError as e:  # General httpx network error
        logger.exception(f"Request error during reservation creation: {e}")
        return False
    except Exception as e:  # Catch-all for other unexpected errors
        logger.exception(f"Unexpected exception during reservation creation: {e}")
        return False

    return False


async def load_client_and_csrf_token(
    *,
    refresh: bool = False,
) -> tuple[httpx.AsyncClient | None, str | None]:
    cache_key_headers = "client_headers"
    cache_key_csrf = "csrf_token"
    cache_key_cookies = "client_cookies_jar"

    if not refresh:
        logger.debug("Attempting to load client data from cache.")
        cached_headers = persistent_cache.get(cache_key_headers)
        cached_csrf = persistent_cache.get(cache_key_csrf)
        cached_cookies_dict = persistent_cache.get(cache_key_cookies)

        if cached_headers and cached_csrf and cached_cookies_dict:
            # Basic validation of cached types
            if not (
                isinstance(cached_headers, dict)
                and isinstance(cached_csrf, str)
                and isinstance(cached_cookies_dict, dict)
            ):
                logger.warning("Cached data type mismatch. Refreshing session.")
            else:
                are_cookie_values_strings = True
                for name, value in cached_cookies_dict.items():
                    if not isinstance(value, str):
                        logger.warning(
                            f"Invalid value type for cookie '{name}' in cache. Refreshing session."
                        )
                        are_cookie_values_strings = False
                        break
                if are_cookie_values_strings:
                    try:
                        client = httpx.AsyncClient(headers=cached_headers)
                        client.cookies.update(cached_cookies_dict)
                        # TODO: Consider a lightweight validation request here to confirm session/CSRF validity
                        logger.info("Using cached client and CSRF token.")
                        return client, cached_csrf
                    except Exception as e:
                        logger.warning(
                            f"Failed to recreate client from cached data: {e}. Refreshing session."
                        )
        else:
            logger.info("One or more items not found in cache. Refreshing session.")
    else:
        logger.info("Explicitly refreshing session and CSRF token (refresh=True).")

    # If cache miss, refresh=True, or cache data was invalid/failed to recreate client:
    fresh_client = httpx.AsyncClient()
    try:
        fresh_client.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3.1 Safari/605.1.15",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

        await login(fresh_client)  # Call await login

        if "login_token" not in fresh_client.cookies:
            logger.error("Login failed (login_token not found). Cannot proceed.")
            await fresh_client.aclose()  # Close the client if login fails
            return None, None

        current_page_content = ""  # Initialize to prevent NameError in except block
        try:
            schedule_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                # Add Referer if necessary, based on browser behavior or server requirements
                # "Referer": BASE_URL # Example if the main page is the referer
            }
            # Assuming BASE_URL is the schedule page URL after login
            # Adjust if a different URL is needed to get the booking CSRF token
            schedule_page_for_csrf = BASE_URL  # or a more specific schedule page URL

            logger.info(
                f"Fetching schedule page for booking CSRF token from: {schedule_page_for_csrf}"
            )
            r_schedule = await fresh_client.get(
                schedule_page_for_csrf,
                headers=schedule_headers,
                timeout=10,
                follow_redirects=True,
            )
            r_schedule.raise_for_status()
            current_page_content = r_schedule.text
            csrf_token = get_csrf_token(current_page_content)
            logger.info(f"Fetched new CSRF Token for booking/actions: {csrf_token}")

        except httpx.HTTPStatusError as e:
            logger.exception(
                f"HTTP error fetching schedule page: {e.response.status_code} - {e.response.text[:500]}"
            )
            await fresh_client.aclose()
            return None, None
        except httpx.RequestError as e:
            logger.exception(f"Request error fetching schedule page: {e}")
            await fresh_client.aclose()
            return None, None
        except ValueError as e:  # For get_csrf_token
            logger.exception(f"Error parsing CSRF from schedule page: {e}")
            if current_page_content:  # Only log if content was fetched
                logger.exception("HTML content for debugging Schedule CSRF:")
                logger.exception(current_page_content[:1500])
            await fresh_client.aclose()
            return None, None
        except Exception as e:  # Catch any other unexpected error during setup
            logger.exception(f"Unexpected error during client setup: {e}")
            await fresh_client.aclose()
            return None, None

        # Successfully logged in and got CSRF, store to cache
        cookies_to_cache = {
            name: value
            for name, value in fresh_client.cookies.items()
            if isinstance(value, str)
        }
        headers_to_cache = dict(fresh_client.headers)

        persistent_cache.set(cache_key_headers, headers_to_cache, expire=6 * 60 * 60)
        persistent_cache.set(cache_key_cookies, cookies_to_cache, expire=6 * 60 * 60)
        persistent_cache.set(cache_key_csrf, csrf_token, expire=6 * 60 * 60)
        logger.info("Successfully fetched and cached new client data and CSRF token.")

        return fresh_client, csrf_token
    except (
        Exception
    ) as e:  # Catch-all for errors during fresh_client instantiation or initial setup
        logger.exception(f"Critical error during fresh client setup: {e}")
        if "fresh_client" in locals() and not fresh_client.is_closed:
            await fresh_client.aclose()
        return None, None


async def main_async() -> None:
    max_retries = 1  # Allow one re-authentication attempt
    retry_count = 0
    client = None  # Initialize client to None

    while retry_count <= max_retries:
        needs_refresh = retry_count > 0  # Refresh if it's a retry attempt
        if (
            client and not client.is_closed
        ):  # Close previous client if it exists and is open
            await client.aclose()
            logger.info("Closed previous client before retry.")

        temp_client, csrf_token = await load_client_and_csrf_token(
            refresh=needs_refresh
        )

        if not temp_client or not csrf_token:
            logger.error("Failed to load client or CSRF token. Aborting.")
            return

        client = temp_client  # Assign to the loop-scoped client

        target_day = date.today() + timedelta(days=7)
        tasks = []
        for resource_id_int in PREFERRED_RANGE:
            resource_id_str = str(resource_id_int)
            tasks.append(
                create_reservation(
                    client=client,  # Use the current client from load_client_and_csrf_token
                    owner_id=OWNER_ID,
                    resource_id=resource_id_str,
                    csrf_token=csrf_token,
                    reservation_date=target_day,
                )
            )

        if not tasks:
            logger.warning("No reservation tasks generated. Check PREFERRED_RANGE.")
            if client and not client.is_closed:
                await client.aclose()
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)

        session_expired_during_batch = False
        count_fail = 0
        success_reservations = []

        processed_resource_ids = list(
            PREFERRED_RANGE
        )  # For matching results to resource IDs

        for i, result in enumerate(results):
            resource_id_attempted = processed_resource_ids[i]
            if isinstance(result, SessionExpiredError):
                logger.error(
                    f"SessionExpiredError for resource {resource_id_attempted}. Re-authentication may be needed."
                )
                session_expired_during_batch = True
                count_fail += 1
            elif isinstance(result, Exception):
                logger.warning(
                    f"Reservation for resource {resource_id_attempted} failed with an exception: {result}"
                )
                count_fail += 1
            elif result is True:
                logger.info(
                    f"Reservation successful for resource {resource_id_attempted} on {target_day}!"
                )
                success_reservations.append(resource_id_attempted)
            else:  # result is False
                logger.info(
                    f"Reservation attempt for resource {resource_id_attempted} returned False."
                )
                count_fail += 1

        logger.info(f"Booking attempt {retry_count + 1} summary:")
        logger.info(f"Failed to book {count_fail} resources in this batch.")
        logger.info(
            f"Successfully booked {len(success_reservations)} resources in this batch: {success_reservations}"
        )

        if session_expired_during_batch:
            if retry_count < max_retries:
                retry_count += 1
                logger.info(
                    f"Session expired. Attempting re-authentication (attempt {retry_count}/{max_retries})."
                )
                # The loop will continue, and load_client_and_csrf_token will be called with refresh=True
            else:
                logger.error(
                    "Session expired and max retries reached. Could not complete bookings."
                )
                break  # Exit retry loop
        else:
            # If no session expiry, break out of the retry loop, regardless of other failures/successes
            # The existing retry logic with time.sleep for general failures can be added here if needed
            logger.info("Batch processed without session expiration.")
            if (
                not success_reservations and booking_details.retry_on_fail
            ):  # Your existing retry logic
                logger.info(
                    f"No reservations successful, and retry_on_fail is True. Waiting {booking_details.retry_delay_seconds}s before general retry."
                )
                # This general retry should ideally also re-evaluate if a CSRF/session refresh is needed
                # For now, it uses the same client and token. If 401s occur here, they won't trigger the specific re-auth.
                time.sleep(booking_details.retry_delay_seconds)
                # This part re-runs tasks without re-auth. Consider if this is what you want
                # or if it should also go through the re-auth loop if it encounters 401s.
                logger.info("Re-attempting failed reservations (general retry)...")
                # Re-create tasks only for those that didn't succeed and weren't SessionExpiredError
                # This requires more sophisticated tracking of failures if you want to be selective.
                # For simplicity, the original code re-appended all tasks. Be mindful of this.
            else:
                break  # No session expiry, and either success or no general retry configured

    if client and not client.is_closed:  # Ensure client is closed at the very end
        await client.aclose()
        logger.info("Final client closed.")


def main() -> None:
    asyncio.run(main_async())


def reload_csrf_token() -> None:
    client, csrf_token = asyncio.run(load_client_and_csrf_token(refresh=True))


if __name__ == "__main__":
    main()
