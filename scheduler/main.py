from __future__ import annotations

import datetime as dt
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any
import pyotp
import requests
from bs4 import BeautifulSoup
from scheduler.config import LoginDetails, BookingDetails

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

booking_details = BookingDetails()
# --- Configuration ---
BASE_URL = booking_details.base_url
LOGIN_PAGE_URL = booking_details.login_page_url
# Let's try posting to index.php without the action=logon first, based on cURL
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


def fetch_schedule_reservations(  # noqa: PLR0913
    session: requests.Session,
    BASE_URL: str,
    schedule_id: int,
    start_date: date,
    end_date: date,
    csrf_token: str,
) -> dict[str, Any] | None:
    FETCH_URL = BASE_URL.rstrip("/") + "/schedule.php?dr=reservations"
    REFERER_URL = BASE_URL.rstrip("/") + f"/schedule.php?scheduleid={schedule_id}"

    # Format dates correctly
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    headers = {
        "Accept": "*/*",
        "Origin": BASE_URL.split("/ub/Web/")[0],
        "Referer": REFERER_URL,
        "X-Requested-With": "XMLHttpRequest",
        # User-Agent, Cookie, Content-Type (multipart) handled by session/requests
    }

    # Prepare multipart form data parts
    # Use (None, value) for non-file form fields
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
        response = session.post(
            FETCH_URL,
            headers=headers,
            files=form_data_parts,  # Use 'files' for multipart/form-data
            timeout=15,
        )
        response.raise_for_status()  # Raise exception for bad status codes (4xx or 5xx)

        logger.info(f"Fetch Response Status: {response.status_code}")

        return response.json()

    except requests.exceptions.RequestException as e:
        logger.exception(f"Error during reservation fetch request: {e}")
        if hasattr(e, "response") and e.response is not None:
            logger.exception(f"Response status: {e.response.status_code}")
            logger.exception(f"Response content: {e.response.text[:500]}")
        return None
    except json.JSONDecodeError as e:
        logger.exception(f"Error decoding JSON response: {e}")
        logger.exception(f"Response Text: {response.text}")
        return None
    except Exception as e:
        logger.exception(f"An unexpected error occurred during reservation fetch: {e}")
        return None


def login(session: requests.Session) -> None:  # noqa: PLR0911, PLR0915
    logger.info("Step 1: Accessing login page to get initial CSRF token and cookies...")
    try:
        r_initial = session.get(LOGIN_PAGE_URL, timeout=10)
        r_initial.raise_for_status()
        logger.info(f"Initial Cookies: {session.cookies.get_dict()}")
        login_headers = {
            "Referer": LOGIN_PAGE_URL,
            "Origin": BASE_URL.rstrip("/"),
        }

    except requests.RequestException as e:
        logger.exception(f"Error getting initial page: {e}")
        return
    except ValueError as e:
        logger.exception(f"Error parsing CSRF: {e}")
        logger.exception("HTML content for debugging CSRF:")
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
        # Post to the updated URL, include specific headers
        r_login = session.post(
            LOGIN_ACTION_URL,
            data=login_payload,
            headers=login_headers,
            allow_redirects=True,
            timeout=10,
        )
        r_login.raise_for_status()
        logger.info(f"Login submission to {r_login.url}, status: {r_login.status_code}")
        logger.debug(f"Cookies after login attempt: {session.cookies.get_dict()}")

        # Check if 2FA page is presented (check URL and content):
        if "passcode" in r_login.text.lower():
            logger.info("2FA step detected.")
            try:
                csrf_token_2fa = get_csrf_token(r_login.text)
                logger.debug(f"2FA Page CSRF Token: {csrf_token_2fa}")
            except ValueError as e:
                logger.exception(f"Error parsing CSRF from 2FA page: {e}")
                logger.exception("HTML content for debugging 2FA CSRF:")
                logger.exception(r_login.text[:1500])
                return  # Cannot proceed without CSRF

            totp_code = generate_totp(TOTP_SECRET)

            tfa_payload = {
                "CSRF_TOKEN": csrf_token_2fa,
                "OTP": totp_code,
            }
            tfa_headers = {
                "Referer": r_login.url,
                "Origin": BASE_URL.rstrip("/"),
            }

            logger.info("\nStep 3: Submitting TOTP code...")
            r_tfa = session.post(
                TFA_VALIDATE_URL,
                data=tfa_payload,
                headers=tfa_headers,
                allow_redirects=True,
                timeout=10,
            )
            r_tfa.raise_for_status()
            logger.info(f"2FA submission to {r_tfa.url}, status: {r_tfa.status_code}")
            logger.info(f"Cookies after 2FA attempt: {session.cookies.get_dict()}")

            if "login_token" in session.cookies.get_dict():
                logger.info("Login successful after 2FA!")
            else:
                logger.exception(
                    "Login failed after 2FA submission (or success indicators not found)."
                )
                logger.exception(f"Response URL: {r_tfa.url}")
                logger.exception(f"Response Text sample: {r_tfa.text[:1000]}")
                return

        # Check for login success indicators if 2FA was NOT detected/required
        else:
            ...
            # TODO(Andy): to implement

    except requests.RequestException as e:
        logger.exception(f"Error during login/2FA HTTP request: {e}")
        if e.response is not None:
            logger.exception(f"Response status: {e.response.status_code}")
            logger.exception(f"Response content: {e.response.text[:500]}")
        return
    except ValueError as e:
        logger.exception(f"Error parsing CSRF during login/2FA process: {e}")
        return
    except Exception as e:
        logger.exception(f"An unexpected error occurred during login/2FA: {e}")
        return


def create_reservation(
    session: requests.Session,
    owner_id: int,
    resource_id: str,
    csrf_token: str,
    reservation_date: date | None = None,
    start_time: dt.datetime | None = None,
    end_time: dt.datetime | None = None,
) -> bool:
    booking_service_url = BASE_URL + "api/reservation.php?action=create"

    if reservation_date:
        start_time = dt.datetime(  # noqa: DTZ001
            reservation_date.year,
            reservation_date.month,
            reservation_date.day,
            PREFERRED_START_TIME_HOUR,
            PREFERRED_START_TIME_MINUTE,
        )
        end_time = dt.datetime(  # noqa: DTZ001
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
        "start": start_iso_str,  # New Start & End
        "end": end_iso_str,
        # --- Recurrence (but not supported by UZH afaik) ---
        "recurrence": {
            "type": "none",
            "interval": 1,
            "weekdays": None,
            "monthlyType": None,
            "weekOfMonth": None,
            "terminationDate": None,
            "repeatDates": [],
        },
        # --- Reminders/Participants (who cares lol) ---
        "startReminder": None,
        "endReminder": None,
        "inviteeIds": [],
        "coOwnerIds": [],
        "participantIds": [],
        "guestEmails": [],
        "participantEmails": [],
        "allowSelfJoin": False,
        # --- Attachments/Approval (leave as is) ---
        "attachments": [],
        "requiresApproval": False,
        # --- Checkin/Checkout ---
        "checkinDate": None,
        "checkoutDate": None,
        # --- Metadata ---
        "termsAcceptedDate": terms_accepted_date_str,
        "attributeValues": STANDARD_ATTRIBUTE_VALUES,  # Change this to your department
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
    }

    try:
        r_create = session.post(
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
            if resp_json.get("success"):
                if resp_json.get("data").get("success"):
                    return True
            if error := resp_json.get("data").get("errors"):
                logger.warning(error)
        except Exception as e:
            logger.exception(f"Error parsing create reservation response as JSON: {e}")
            return False
    except Exception as e:
        logger.exception(f"Exception during reservation creation: {e}")
        return False

    return False

    # TODO(Andy): error messages:
    # 1.["Die Reservierung liegt zu weit in der Zukunft. Der sp\u00e4teste Zeitpunkt ist 19\/05\/2025 23:59:00."]
    # 2.       "Es ist nur eine Reservierung zur selben Zeit m\u00f6glich.\n20/05/2025\n"
    # 3.       "Es gibt in Konflikt stehende Reservierungen an folgenden Tagen:\n20/05/2025"


def update_reservation(
    session: requests.Session,
    target_reference_number: str,
    owner_id: int,
    resource_id: str,
    start_time: dt.datetime,
    end_time: dt.datetime,
    csrf_token: str,
    schedule_page_url: str,
) -> None:
    booking_service_url = BASE_URL + "api/reservation.php?action=update"

    # --- Define the NEW desired start and end times for the update ---
    # SHIFT HOWEVER BY -2 HRS I THINK hAS TO DO WITH UTC
    target_dt_start = dt.datetime(2025, 5, 12, 14, 30, 0)
    target_dt_end = dt.datetime(2025, 5, 12, 15, 0, 0)

    # I am not quite sure hwat this is, it seems to match the original booking date but I am not sure.
    checkin_date_str_from_curl = "2025-05-12T14:00:00.000Z"

    # Format NEW start/end times as ISO 8601 UTC
    start_iso_str = target_dt_start.isoformat(timespec="milliseconds") + "Z"
    end_iso_str = target_dt_end.isoformat(timespec="milliseconds") + "Z"
    # Terms accepted date is likely still the current time for the update action
    terms_accepted_date_str = datetime.now().isoformat(timespec="milliseconds") + "Z"

    # --- JSON Payload Structure Update for UPDATE action ---
    # Based on the 'action=update' cURL command's JSON payload
    reservation_details = {
        # --- Identifier ---
        "referenceNumber": target_reference_number,  # <<< MUST provide the ref number to update
        "ownerId": owner_id,
        "resourceIds": [TARGET_RESOURCE_ID],
        "accessories": [],
        "title": "",
        "description": "",
        "start": start_iso_str,  # New Start & End
        "end": end_iso_str,
        # --- Recurrence (but not supported by UZH afaik) ---
        "recurrence": {
            "type": "none",
            "interval": 1,
            "weekdays": None,
            "monthlyType": None,
            "weekOfMonth": None,
            "terminationDate": None,
            "repeatDates": [],
        },
        # --- Reminders/Participants (who cares lol) ---
        "startReminder": None,
        "endReminder": None,
        "inviteeIds": [],
        "coOwnerIds": [],
        "participantIds": [],
        "guestEmails": [],
        "participantEmails": [],
        "allowSelfJoin": False,
        # --- Attachments/Approval (leave as is) ---
        "attachments": [],
        "requiresApproval": False,
        # --- Checkin/Checkout ---
        "checkinDate": checkin_date_str_from_curl,
        "checkoutDate": None,
        # --- Metadata ---
        "termsAcceptedDate": terms_accepted_date_str,
        "attributeValues": STANDARD_ATTRIBUTE_VALUES,  # Change this to your department
        "meetingLink": None,
        "displayColor": None,
    }

    api_request_payload = {
        "reservation": reservation_details,
        "retryParameters": [],
        "updateScope": "full",
    }

    logger.info(f"Attempting UPDATE for reservation ref: {target_reference_number}")
    logger.info(f"Using API Endpoint: {booking_service_url}")
    logger.info(f"New Time (ISO UTC): From {start_iso_str} To {end_iso_str}")
    logger.info(f"JSON Payload for 'request' part: {json.dumps(api_request_payload)}")

    # --- Multipart Form Data Update (Structure remains the same) ---
    booking_form_parts = {
        "request": (None, json.dumps(api_request_payload), "application/json"),
        "CSRF_TOKEN": (None, csrf_token),
        "BROWSER_TIMEZONE": (None, "Europe/Zurich"),
    }

    # --- Headers Update (Structure remains the same, ensure Origin is correct) ---
    booking_headers = {
        "Referer": schedule_page_url,
        "Origin": BASE_URL.rstrip("/"),  # <<< Correct Origin based on cURL examples
        "Accept": "application/json",
        "X-Csrf-Token": csrf_token,
    }
    logger.info(f"Update Headers: {booking_headers}")

    # --- Execute Update Request (Code remains the same, uses updated URL/payload/headers) ---
    try:
        # This POST now goes to the 'action=update' URL with the update payload
        r_update = session.post(
            booking_service_url,
            files=booking_form_parts,
            headers=booking_headers,
            timeout=15,
        )
        r_update.raise_for_status()  # Check for HTTP errors (4xx, 5xx)

        logger.info(f"\nUpdate POST complete. Status: {r_update.status_code}")
        logger.info(f"Update Response Headers: {r_update.headers}")
        logger.info(f"Update Response (first 500 chars): {r_update.text[:500]}")

        # --- Process Response (Check for success/failure specific to update) ---
        try:
            response_data = r_update.json()
            logger.info(f"Update Response JSON: {json.dumps(response_data, indent=2)}")

            # TODO(Andy): we need response_data.get("data").get("success")
            # Check common success indicators for update actions
            if response_data.get("data", {}).get("success") is True:
                logger.info(
                    ">>> Reservation UPDATE SUCCESSFUL! (Based on API JSON response) <<<"
                )
            elif response_data.get("errors"):
                logger.exception(
                    f"Update FAILED. API Errors: {response_data['errors']}"
                )
            elif response_data.get("message"):
                logger.exception(
                    f"Update FAILED/INFO. API Message: {response_data['message']}"
                )
            else:
                # Check the inner 'data' object structure if the outer one isn't clear
                inner_data = response_data.get("data", {})
                if inner_data.get("success") is False and inner_data.get("errors"):
                    logger.exception(
                        f"Update FAILED. API Errors (inner): {inner_data['errors']}"
                    )
                elif inner_data.get("success") is True:
                    logger.info(
                        ">>> Reservation UPDATE likely SUCCESSFUL! (Based on inner 'data' object) <<<"
                    )
                else:
                    logger.info(
                        "Update status uncertain. Success/error indicators not found in JSON response."
                    )

        except json.JSONDecodeError:
            logger.exception(">>> Update FAILED: API response was not valid JSON. <<<")
            logger.exception(
                f"Full Response Text (first 1000 chars): {r_update.text[:1000]}"
            )

    except requests.RequestException as e:
        logger.exception(f"Error during update API request: {e}")
        if e.response is not None:
            logger.exception(f"Response status: {e.response.status_code}")
            logger.exception(f"Response content: {e.response.text[:500]}")
    except Exception as e:
        logger.exception(f"An unexpected error occurred during update: {e}")


def main() -> None:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3.1 Safari/605.1.15",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )

    login(session)

    # --- At this point, we should be logged in ---

    # --- Fetch Schedule Page for Booking CSRF ---
    try:
        schedule_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        r_schedule = session.get(BASE_URL, headers=schedule_headers, timeout=10)
        r_schedule.raise_for_status()
        current_page_content = r_schedule.text
        csrf_token = get_csrf_token(current_page_content)
        logger.debug(f"CSRF Token for booking: {csrf_token}")
    except requests.RequestException as e:
        logger.exception(f"Error fetching schedule page: {e}")
        return
    except ValueError as e:
        logger.exception(f"Error parsing CSRF from schedule page: {e}")
        logger.exception("HTML content for debugging Schedule CSRF:")
        logger.exception(current_page_content[:1500])
        return
    except NameError:
        logger.exception(
            "Login did not complete successfully, cannot proceed to fetch schedule page."
        )
        return

    target_day = date.today() + timedelta(days=7)  # today + a week
    for resource_id in PREFERRED_RANGE:
        reservation_success = create_reservation(
            session=session,
            owner_id=OWNER_ID,
            resource_id=str(resource_id),
            csrf_token=csrf_token,
            reservation_date=target_day,
        )
        if reservation_success:
            logger.info(f"Reservation successful for resource {resource_id}")
            return
        else:
            logger.info(f"Reservation failed for resource {resource_id}")


if __name__ == "__main__":
    main()
