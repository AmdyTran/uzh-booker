from diskcache import Cache
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
    base_url: str = "https://ubbooked01.ub.uzh.ch/ub/Web/"
    login_page_url: str = base_url + "index.php"
    login_action_url: str = base_url + "index.php"
    tfa_validate_url: str = base_url + "auth/confirm-account.php?action=Confirm"
    owner_id: int = 1843

    # SELECTED SPOTS CONFIGURATION
    # Generated from spot selector with 0 spots
    selected_resource_ids: list[int] = []

    # Legacy range settings (not used when selected_resource_ids is provided)
    preferred_range_start: int = 231
    preferred_range_end: int = 263

    # Booking time settings
    preferred_start_time_hour: int = 6
    preferred_start_time_minute: int = 30
    preferred_end_time_hour: int = 16
    preferred_end_time_minute: int = 30

    # Booking attributes
    standard_attribute_values: list[dict[str, str]] = [{"id": "1", "value": "WWF"}]

    @property
    def resource_ids_to_book(self) -> list[int]:
        """Get the resource IDs to attempt booking."""
        if self.selected_resource_ids:
            return self.selected_resource_ids
        else:
            # Fallback to range if no specific spots selected
            return list(range(self.preferred_range_start, self.preferred_range_end))
