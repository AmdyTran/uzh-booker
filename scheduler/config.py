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


class BookingDetails(BaseModel):
    base_url: str = "https://ubbooked01.ub.uzh.ch/ub/Web/"
    login_page_url: str = base_url + "index.php"
    login_action_url: str = base_url + "index.php"
    tfa_validate_url: str = base_url + "auth/confirm-account.php?action=Confirm"
    owner_id: int = 1843
    preferred_range_start: int = 231
    preferred_range_end: int = 263
    preferred_start_time_hour: int = 6
    preferred_start_time_minute: int = 30
    preferred_end_time_hour: int = 16
    preferred_end_time_minute: int = 30
    standard_attribute_values: list[dict[str, str]] = [{"id": "1", "value": "WWF"}]
