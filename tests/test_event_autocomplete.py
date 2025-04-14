# tests/test_main_autocomplete.py

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

# Import the module containing the autocomplete functions
from offkai_bot import main

# Import the Event dataclass to create test data
from offkai_bot.data.event import Event

# pytest marker for async tests
pytestmark = pytest.mark.asyncio

# --- Test Data Fixtures ---


@pytest.fixture
def mock_interaction():
    """Fixture to create a basic mock discord.Interaction."""
    interaction = MagicMock(spec=discord.Interaction)
    return interaction


@pytest.fixture
def sample_events():
    """Fixture providing a list of sample Event objects for testing."""
    now = datetime.now()
    return [
        Event(
            event_name="Summer Party",
            venue="Beach",
            address="123",
            google_maps_link="g1",
            open=True,
            archived=False,
            event_datetime=now,
        ),
        Event(
            event_name="Winter Gathering",
            venue="Lodge",
            address="456",
            google_maps_link="g2",
            open=False,
            archived=False,
            event_datetime=now,
        ),
        Event(
            event_name="Spring Fling",
            venue="Park",
            address="789",
            google_maps_link="g3",
            open=True,
            archived=False,
            event_datetime=now,
        ),
        Event(
            event_name="Autumn Festival",
            venue="Field",
            address="101",
            google_maps_link="g4",
            open=False,
            archived=False,
            event_datetime=now,
        ),
        Event(
            event_name="Archived Event",
            venue="Past",
            address="Old",
            google_maps_link="g5",
            open=False,
            archived=True,
            event_datetime=now,
        ),  # Archived
        Event(
            event_name="Summer BBQ",
            venue="Backyard",
            address="112",
            google_maps_link="g6",
            open=True,
            archived=False,
            event_datetime=now,
        ),  # Another open one
    ]


# --- Tests for event_autocomplete_base ---


@patch("offkai_bot.main.load_event_data")  # Patch where load_event_data is USED
async def test_autocomplete_base_no_events(mock_load_data, mock_interaction):
    """Test autocomplete when no events are loaded."""
    mock_load_data.return_value = []
    choices = await main.event_autocomplete_base(mock_interaction, current="", open_status=None)
    assert choices == []
    mock_load_data.assert_called_once()


@patch("offkai_bot.main.load_event_data")
async def test_autocomplete_base_no_current_all_open_status(mock_load_data, mock_interaction, sample_events):
    """Test autocomplete with empty 'current' and no open_status filter."""
    mock_load_data.return_value = sample_events
    choices = await main.event_autocomplete_base(mock_interaction, current="", open_status=None)
    # Should return all non-archived events
    expected_names = {"Summer Party", "Winter Gathering", "Spring Fling", "Autumn Festival", "Summer BBQ"}
    returned_names = {choice.value for choice in choices}
    assert len(choices) == 5
    assert returned_names == expected_names


@patch("offkai_bot.main.load_event_data")
async def test_autocomplete_base_no_current_open_only(mock_load_data, mock_interaction, sample_events):
    """Test autocomplete with empty 'current' filtering for open=True."""
    mock_load_data.return_value = sample_events
    choices = await main.event_autocomplete_base(mock_interaction, current="", open_status=True)
    # Should return only open, non-archived events
    expected_names = {"Summer Party", "Spring Fling", "Summer BBQ"}
    returned_names = {choice.value for choice in choices}
    assert len(choices) == 3
    assert returned_names == expected_names


@patch("offkai_bot.main.load_event_data")
async def test_autocomplete_base_no_current_closed_only(mock_load_data, mock_interaction, sample_events):
    """Test autocomplete with empty 'current' filtering for open=False."""
    mock_load_data.return_value = sample_events
    choices = await main.event_autocomplete_base(mock_interaction, current="", open_status=False)
    # Should return only closed, non-archived events
    expected_names = {"Winter Gathering", "Autumn Festival"}
    returned_names = {choice.value for choice in choices}
    assert len(choices) == 2
    assert returned_names == expected_names


@patch("offkai_bot.main.load_event_data")
async def test_autocomplete_base_partial_match_case_insensitive(mock_load_data, mock_interaction, sample_events):
    """Test autocomplete with partial, case-insensitive 'current' string."""
    mock_load_data.return_value = sample_events
    choices = await main.event_autocomplete_base(mock_interaction, current="sum", open_status=None)
    # Should match "Summer Party" and "Summer BBQ"
    expected_names = {"Summer Party", "Summer BBQ"}
    returned_names = {choice.value for choice in choices}
    assert len(choices) == 2
    assert returned_names == expected_names


@patch("offkai_bot.main.load_event_data")
async def test_autocomplete_base_partial_match_with_open_filter(mock_load_data, mock_interaction, sample_events):
    """Test autocomplete with partial 'current' and open=False filter."""
    mock_load_data.return_value = sample_events
    choices = await main.event_autocomplete_base(mock_interaction, current="fest", open_status=False)
    # Should match "Autumn Festival" (which is closed)
    expected_names = {"Autumn Festival"}
    returned_names = {choice.value for choice in choices}
    assert len(choices) == 1
    assert returned_names == expected_names


@patch("offkai_bot.main.load_event_data")
async def test_autocomplete_base_no_match(mock_load_data, mock_interaction, sample_events):
    """Test autocomplete when 'current' matches no events."""
    mock_load_data.return_value = sample_events
    choices = await main.event_autocomplete_base(mock_interaction, current="xyz", open_status=None)
    assert choices == []


@patch("offkai_bot.main.load_event_data")
async def test_autocomplete_base_archived_excluded(mock_load_data, mock_interaction, sample_events):
    """Test that archived events are always excluded."""
    mock_load_data.return_value = sample_events
    # Try matching the archived event name
    choices = await main.event_autocomplete_base(mock_interaction, current="Archived", open_status=None)
    assert choices == []
    choices_open = await main.event_autocomplete_base(mock_interaction, current="Archived", open_status=True)
    assert choices_open == []
    choices_closed = await main.event_autocomplete_base(mock_interaction, current="Archived", open_status=False)
    assert choices_closed == []


@patch("offkai_bot.main.load_event_data")
async def test_autocomplete_base_limit_choices(mock_load_data, mock_interaction):
    """Test that the number of choices is limited to 25."""
    # Create 30 matching events
    events = [
        Event(
            event_name=f"Event {i}",
            venue="V",
            address="A",
            google_maps_link="G",
            open=True,
            archived=False,
            event_datetime=datetime.now(),
        )
        for i in range(30)
    ]
    mock_load_data.return_value = events
    choices = await main.event_autocomplete_base(mock_interaction, current="Event", open_status=None)
    assert len(choices) == 25  # Discord limit


# --- Tests for Wrapper Autocomplete Functions ---


@patch("offkai_bot.main.event_autocomplete_base", new_callable=AsyncMock)  # Mock the base function
async def test_offkai_autocomplete_active(mock_base_autocomplete, mock_interaction):
    """Test that offkai_autocomplete_active calls base with open_status=None."""
    current_str = "test"
    await main.offkai_autocomplete_active(mock_interaction, current_str)
    mock_base_autocomplete.assert_awaited_once_with(mock_interaction, current_str, open_status=None)


@patch("offkai_bot.main.event_autocomplete_base", new_callable=AsyncMock)
async def test_offkai_autocomplete_closed_only(mock_base_autocomplete, mock_interaction):
    """Test that offkai_autocomplete_closed_only calls base with open_status=False."""
    current_str = "closed"
    await main.offkai_autocomplete_closed_only(mock_interaction, current_str)
    mock_base_autocomplete.assert_awaited_once_with(mock_interaction, current_str, open_status=False)


@patch("offkai_bot.main.event_autocomplete_base", new_callable=AsyncMock)
async def test_offkai_autocomplete_all_non_archived(mock_base_autocomplete, mock_interaction):
    """Test that offkai_autocomplete_all_non_archived calls base with open_status=None."""
    current_str = "any"
    await main.offkai_autocomplete_all_non_archived(mock_interaction, current_str)
    # Currently calls with open_status=None, same as _active
    mock_base_autocomplete.assert_awaited_once_with(mock_interaction, current_str, open_status=None)
