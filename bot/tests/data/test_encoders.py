# src/offkai_bot/tests/test_encoders.py  (You might need to create a 'tests' directory)

import json
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime

# Assuming your project structure allows this import
# Adjust the path if necessary based on how you run tests
from offkai_bot.data.encoders import DataclassJSONEncoder


# --- Test Data Structures ---
@dataclass
class SimpleData:
    name: str
    value: int


@dataclass
class DataWithDatetime:
    description: str
    timestamp: datetime
    count: int | None = None


@dataclass
class DataWithOptionalDatetime:
    event: str
    start_time: datetime | None = None


@dataclass
class NestedData:
    outer_id: int
    inner_data: SimpleData
    event_time: datetime


class NonSerializable:
    pass


# --- Test Cases ---
class TestDataclassJSONEncoder(unittest.TestCase):
    def test_simple_dataclass(self):
        """Test encoding a simple dataclass without datetime."""
        instance = SimpleData(name="Test", value=123)
        expected_json = '{"name": "Test", "value": 123}'
        # Use json.dumps with the custom encoder
        result_json = json.dumps(instance, cls=DataclassJSONEncoder)
        # Compare loaded dicts for robustness against key order issues
        self.assertEqual(json.loads(result_json), json.loads(expected_json))

    def test_dataclass_with_datetime(self):
        """Test encoding a dataclass containing a datetime object."""
        now = datetime.now(UTC)  # Use timezone-aware datetime
        instance = DataWithDatetime(description="Measurement", timestamp=now, count=5)
        expected_dict = {
            "description": "Measurement",
            "timestamp": now.isoformat(),  # Expect ISO format string
            "count": 5,
        }
        result_json = json.dumps(instance, cls=DataclassJSONEncoder)
        self.assertEqual(json.loads(result_json), expected_dict)

    def test_dataclass_with_none_datetime(self):
        """Test encoding a dataclass where an optional datetime is None."""
        instance = DataWithOptionalDatetime(event="Meeting", start_time=None)
        expected_dict = {
            "event": "Meeting",
            "start_time": None,  # Expect None to be preserved
        }
        result_json = json.dumps(instance, cls=DataclassJSONEncoder)
        self.assertEqual(json.loads(result_json), expected_dict)

    def test_dataclass_with_naive_datetime(self):
        """Test encoding a dataclass containing a naive datetime object."""
        naive_dt = datetime(2023, 10, 27, 10, 30, 0)
        instance = DataWithDatetime(description="Naive Test", timestamp=naive_dt)
        expected_dict = {
            "description": "Naive Test",
            "timestamp": naive_dt.isoformat(),  # Expect ISO format string
            "count": None,
        }
        result_json = json.dumps(instance, cls=DataclassJSONEncoder)
        self.assertEqual(json.loads(result_json), expected_dict)

    def test_nested_dataclass_with_datetime(self):
        """Test encoding a nested dataclass with a datetime."""
        now = datetime.now(UTC)
        inner = SimpleData(name="Inner", value=456)
        outer = NestedData(outer_id=1, inner_data=inner, event_time=now)
        expected_dict = {
            "outer_id": 1,
            "inner_data": {"name": "Inner", "value": 456},  # Nested dataclass becomes dict
            "event_time": now.isoformat(),
        }
        result_json = json.dumps(outer, cls=DataclassJSONEncoder, indent=4)  # Use indent for readability if needed
        # print(f"\nNested Result JSON:\n{result_json}") # Optional: print for debugging
        self.assertEqual(json.loads(result_json), expected_dict)

    def test_non_dataclass_object(self):
        """Test encoding a standard dictionary (should fall back to default)."""
        data = {"key": "value", "number": 10, "list": [1, 2]}
        expected_json = '{"key": "value", "number": 10, "list": [1, 2]}'
        result_json = json.dumps(data, cls=DataclassJSONEncoder)
        self.assertEqual(json.loads(result_json), json.loads(expected_json))

    def test_non_serializable_object(self):
        """Test encoding an object not handled by default JSONEncoder."""
        instance = NonSerializable()
        # Expect a TypeError because the default encoder can't handle this
        with self.assertRaises(TypeError):
            json.dumps(instance, cls=DataclassJSONEncoder)

    def test_list_of_dataclasses(self):
        """Test encoding a list containing dataclasses."""
        now = datetime.now(UTC)
        dt1 = now
        dt2 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        data_list = [
            DataWithDatetime(description="Item 1", timestamp=dt1, count=1),
            DataWithDatetime(description="Item 2", timestamp=dt2, count=None),
        ]
        expected_list = [
            {"description": "Item 1", "timestamp": dt1.isoformat(), "count": 1},
            {"description": "Item 2", "timestamp": dt2.isoformat(), "count": None},
        ]
        result_json = json.dumps(data_list, cls=DataclassJSONEncoder)
        self.assertEqual(json.loads(result_json), expected_list)


# To run the tests (place this at the end of the file):
if __name__ == "__main__":
    unittest.main()
