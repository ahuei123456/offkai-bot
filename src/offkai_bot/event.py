from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Event:
    event_name: str
    venue: str
    address: str
    google_maps_link: str
    event_datetime: datetime | None = None
    message: str | None = None

    channel_id: int | None = None
    message_id: int | None = None
    open: bool = False
    archived: bool = False
    drinks: list[str] = field(default_factory=list)

    @property
    def has_drinks(self):
        return len(self.drinks) > 0

    def format_details(self):
        dt_str = self.event_datetime.strftime(r"%Y-%m-%d %H:%M") + " JST" if self.event_datetime else "Not Set"
        drinks_str = ", ".join(self.drinks) if self.drinks else "No selection needed!"
        return (
            f"📅 **Event Name**: {self.event_name}\n"
            f"🍽️ **Venue**: {self.venue}\n"
            f"📍 **Address**: {self.address}\n"
            f"🌎 **Google Maps Link**: {self.google_maps_link}\n"
            f"🕑 **Date and Time**: {dt_str}\n"
            f"🍺 **Drinks**: {drinks_str}"
        )

    def __str__(self):
        return self.format_details()


@dataclass
class Response:
    user_id: int
    username: str
    extra_people: int
    behavior_confirmed: bool
    arrival_confirmed: bool
    event_name: str
    timestamp: datetime
    drinks: list[str] = field(default_factory=list)
