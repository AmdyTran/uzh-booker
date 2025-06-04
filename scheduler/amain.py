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
) -> tuple[httpx.AsyncClient, str]:
    if not refresh and (
        "client_headers" in persistent_cache
        and "csrf_token" in persistent_cache
        and "client_cookies_jar" in persistent_cache
    ):
        client_headers = persistent_cache.get("client_headers")
        csrf_token = persistent_cache.get("csrf_token")
        client_cookies_jar = persistent_cache.get("client_cookies_jar")
        client = httpx.AsyncClient(headers=client_headers)
        client.cookies.jar._cookies.update(client_cookies_jar)
        client.cookies.jar.clear_expired_cookies()

        logger.info("Using cached client and CSRF token")
        return client, csrf_token
    else:
        client = httpx.AsyncClient()
        client.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3.1 Safari/605.1.15",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

        await login(client)  # Call await login

        # Check if login was successful, e.g., by checking for a specific cookie
        if "login_token" not in client.cookies:
            logger.error("Login failed, cannot proceed. Check logs for details.")
            return

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
            r_schedule = await client.get(
                schedule_page_for_csrf,
                headers=schedule_headers,
                timeout=10,
                follow_redirects=True,
            )
            r_schedule.raise_for_status()
            current_page_content = r_schedule.text
            csrf_token = get_csrf_token(current_page_content)
            logger.info(f"CSRF Token for booking/actions: {csrf_token}")

        except httpx.HTTPStatusError as e:
            logger.exception(
                f"HTTP error fetching schedule page: {e.response.status_code} - {e.response.text[:500]}"
            )
            return
        except httpx.RequestError as e:
            logger.exception(f"Request error fetching schedule page: {e}")
            return
        except ValueError as e:  # For get_csrf_token
            logger.exception(f"Error parsing CSRF from schedule page: {e}")
            if current_page_content:  # Only log if content was fetched
                logger.exception("HTML content for debugging Schedule CSRF:")
                logger.exception(current_page_content[:1500])
            return

        client_cookies_jar = client.cookies.jar._cookies
        client_headers = client.headers
        persistent_cache.set("client_headers", client_headers, expire=6 * 60 * 60)
        persistent_cache.set(  # type: ignore
            "client_cookies_jar", client_cookies_jar, expire=6 * 60 * 60
        )
        persistent_cache.set("csrf_token", csrf_token, expire=6 * 60 * 60)

        return client, csrf_token


async def main_async() -> None:
    client, csrf_token = await load_client_and_csrf_token()

    target_day = date.today() + timedelta(days=7)
    tasks = []
    for resource_id_int in PREFERRED_RANGE:
        resource_id_str = str(resource_id_int)
        tasks.append(
            create_reservation(
                client=client,
                owner_id=OWNER_ID,
                resource_id=resource_id_str,
                csrf_token=csrf_token,
                reservation_date=target_day,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    count_fail = 0
    success_reservations = []
    for i, resource_id_attempted in enumerate(PREFERRED_RANGE):
        result = results[i]
        if isinstance(result, Exception):
            count_fail += 1
        elif result is True:
            logger.info(
                f"Reservation successful for resource {resource_id_attempted} on {target_day}!"
            )
            success_reservations.append(resource_id_attempted)
        else:
            count_fail += 1

    logger.info(f"Failed to book {count_fail} resources.")
    logger.info(
        f"Successfully booked {len(success_reservations)} resources: {success_reservations}"
    )

    # TODO(Andy): this is dirty and not clean but oh well
    if not success_reservations:
        logger.info("No reservations were successful, trying again in 20 seconds...")
        time.sleep(15)
        for resource_id_int in PREFERRED_RANGE:
            resource_id_str = str(resource_id_int)
            tasks.append(
                create_reservation(
                    client=client,
                    owner_id=OWNER_ID,
                    resource_id=resource_id_str,
                    csrf_token=csrf_token,
                    reservation_date=target_day,
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        count_fail = 0
        success_reservations = []
        for i, resource_id_attempted in enumerate(PREFERRED_RANGE):
            result = results[i]
            if isinstance(result, Exception):
                count_fail += 1
            elif result is True:
                logger.info(
                    f"Reservation successful for resource {resource_id_attempted} on {target_day}!"
                )
                success_reservations.append(resource_id_attempted)
            else:
                count_fail += 1

        logger.info(f"Failed to book {count_fail} resources.")
        logger.info(
            f"Successfully booked {len(success_reservations)} resources: {success_reservations}"
        )


def main() -> None:
    asyncio.run(main_async())


def reload_csrf_token() -> None:
    client, csrf_token = asyncio.run(load_client_and_csrf_token(refresh=True))


if __name__ == "__main__":
    main()
