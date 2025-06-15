"""
Helper functions to fetch available booking spots from UZH booking system.

This module provides functions to discover available schedules and resources
for the interactive spot selection interface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx
from bs4 import BeautifulSoup

from scheduler.config import BookingConstants


@dataclass
class BookingSpot:
    """Represents a bookable spot/resource."""

    id: int
    name: str
    schedule_id: int
    schedule_name: str
    href: str
    can_book: bool = True


@dataclass
class Schedule:
    """Represents a booking schedule (library)."""

    id: int
    name: str
    selected: bool = False


async def fetch_available_schedules(client: httpx.AsyncClient) -> list[Schedule]:
    """
    Fetch all available schedules (libraries) from the booking system.

    Args:
        client: Authenticated HTTP client

    Returns:
        List of available schedules
    """
    try:
        response = await client.get(
            "https://ubbooked01.ub.uzh.ch/ub/Web/schedule.php",
            timeout=BookingConstants.DEFAULT_TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        schedules = []

        # Find the schedule dropdown
        schedule_select = soup.find("select", {"id": "schedules"})
        if schedule_select:
            for option in schedule_select.find_all("option"):
                schedule_id = int(option.get("value", 0))
                schedule_name = option.get_text(strip=True)
                is_selected = option.get("selected") is not None

                if schedule_id > 0:  # Skip invalid entries
                    schedules.append(
                        Schedule(
                            id=schedule_id, name=schedule_name, selected=is_selected
                        )
                    )

        return schedules

    except Exception as e:
        print(f"Error fetching schedules: {e}")
        return []


async def fetch_spots_for_schedule(
    client: httpx.AsyncClient, schedule_id: int
) -> list[BookingSpot]:
    """
    Fetch all available booking spots for a specific schedule.

    Args:
        client: Authenticated HTTP client
        schedule_id: ID of the schedule to fetch spots for

    Returns:
        List of booking spots for the schedule
    """
    try:
        response = await client.get(
            f"https://ubbooked01.ub.uzh.ch/ub/Web/schedule.php?sid={schedule_id}",
            timeout=BookingConstants.DEFAULT_TIMEOUT,
        )
        response.raise_for_status()

        spots = []

        # Extract JavaScript reservationResources array
        js_pattern = r"reservationResources\.push\(\{([^}]+)\}\);"
        matches = re.findall(js_pattern, response.text, re.DOTALL)

        # Get schedule name from the page
        soup = BeautifulSoup(response.text, "html.parser")
        schedule_name = "Unknown"
        schedule_select = soup.find("select", {"id": "schedules"})
        if schedule_select:
            selected_option = schedule_select.find("option", {"selected": True})
            if selected_option:
                schedule_name = selected_option.get_text(strip=True)

        for match in matches:
            # Parse the JavaScript object
            spot_data = _parse_js_object(match)
            if spot_data and "id" in spot_data and "name" in spot_data:
                spots.append(
                    BookingSpot(
                        id=int(spot_data["id"]),
                        name=spot_data["name"].strip('"'),
                        schedule_id=schedule_id,
                        schedule_name=schedule_name,
                        href=spot_data.get("href", "").strip('"'),
                        can_book=spot_data.get("canBook", "true").lower() == "true",
                    )
                )

        return sorted(spots, key=lambda x: x.name)

    except Exception as e:
        print(f"Error fetching spots for schedule {schedule_id}: {e}")
        return []


def _parse_js_object(js_content: str) -> dict[str, Any]:
    """
    Parse a JavaScript object string into a Python dict.

    This is a simple parser for the specific format used in the booking system.
    """
    result = {}

    # Split by lines and parse key-value pairs
    lines = js_content.strip().split("\n")
    for line in lines:
        line = line.strip().rstrip(",")
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            # Remove quotes from key
            if key.startswith('"') and key.endswith('"'):
                key = key[1:-1]

            # Parse value
            if value.lower() == "true":
                value = True
            elif value.lower() == "false":
                value = False
            elif value.isdigit():
                value = int(value)

            result[key] = value

    return result


async def get_all_available_spots(
    client: httpx.AsyncClient,
) -> dict[str, list[BookingSpot]]:
    """
    Fetch all available spots from all schedules.

    Args:
        client: Authenticated HTTP client

    Returns:
        Dictionary mapping schedule names to lists of spots
    """
    schedules = await fetch_available_schedules(client)
    all_spots = {}

    for schedule in schedules:
        spots = await fetch_spots_for_schedule(client, schedule.id)
        if spots:
            all_spots[schedule.name] = spots

    return all_spots


async def search_spots_by_name(
    client: httpx.AsyncClient, search_term: str
) -> list[BookingSpot]:
    """
    Search for spots by name across all schedules.

    Args:
        client: Authenticated HTTP client
        search_term: Term to search for in spot names

    Returns:
        List of matching spots
    """
    all_spots = await get_all_available_spots(client)
    matching_spots = []

    search_lower = search_term.lower()

    for spots_list in all_spots.values():
        for spot in spots_list:
            if search_lower in spot.name.lower():
                matching_spots.append(spot)

    return sorted(matching_spots, key=lambda x: (x.schedule_name, x.name))
