# src/offkai_bot/data/encoders.py
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime


class DataclassJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for dataclasses, converting datetimes to ISO format."""

    def default(self, o):
        if is_dataclass(o):
            data = asdict(o)
            # Convert datetime objects to ISO strings
            for key, value in data.items():
                if isinstance(value, datetime):
                    data[key] = value.isoformat()
            return data
        return super().default(o)
