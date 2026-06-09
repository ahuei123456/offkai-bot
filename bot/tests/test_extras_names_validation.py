"""Tests for extras names validation functionality."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from offkai_bot.data.event import Event
from offkai_bot.interactions import GatheringModal, ValidationError

# --- Fixtures ---


@pytest.fixture
def mock_interaction():
    """Fixture to create a mock discord.Interaction."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 123
    interaction.user.name = "TestUser"
    interaction.channel = MagicMock(spec=discord.Thread)
    interaction.channel.id = 456
    interaction.channel.send = AsyncMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


@pytest.fixture
def sample_event():
    """Create a sample event for testing."""
    now = datetime.now(UTC)
    event_dt = now + timedelta(days=30)
    deadline_dt = now + timedelta(days=7)
    return Event(
        event_name="Test Event",
        venue="Test Venue",
        address="123 Test St",
        google_maps_link="https://maps.google.com/test",
        event_datetime=event_dt,
        event_deadline=deadline_dt,
        channel_id=456,
        thread_id=789,
        message_id=None,
        open=True,
        archived=False,
        drinks=[],
        max_capacity=None,
    )


# --- Tests for _validate_extra_people_names ---


@pytest.mark.asyncio
async def test_validate_extra_people_names_empty_string_no_extras(sample_event):
    """Test validation with empty string when no extra people expected."""
    modal = GatheringModal(event=sample_event)
    names = modal._validate_extra_people_names("", 0)
    assert names == []


@pytest.mark.asyncio
async def test_validate_extra_people_names_whitespace_no_extras(sample_event):
    """Test validation with whitespace when no extra people expected."""
    modal = GatheringModal(event=sample_event)
    names = modal._validate_extra_people_names("   ", 0)
    assert names == []


@pytest.mark.asyncio
async def test_validate_extra_people_names_non_empty_no_extras(sample_event):
    """Test validation raises error when names are provided but 0 extras expected."""
    modal = GatheringModal(event=sample_event)
    with pytest.raises(ValidationError) as exc_info:
        modal._validate_extra_people_names("Alice", 0)
    assert "You specified 0 extra people" in str(exc_info.value)


@pytest.mark.asyncio
async def test_validate_extra_people_names_correct_count(sample_event):
    """Test validation with correct number of names."""
    modal = GatheringModal(event=sample_event)
    names = modal._validate_extra_people_names("Alice,Bob", 2)
    assert names == ["Alice", "Bob"]


@pytest.mark.asyncio
async def test_validate_extra_people_names_single_name(sample_event):
    """Test validation with single extra person."""
    modal = GatheringModal(event=sample_event)
    names = modal._validate_extra_people_names("Charlie", 1)
    assert names == ["Charlie"]


@pytest.mark.asyncio
async def test_validate_extra_people_names_with_spaces(sample_event):
    """Test validation with names containing spaces."""
    modal = GatheringModal(event=sample_event)
    names = modal._validate_extra_people_names("Alice Smith, Bob Jones, Charlie Brown", 3)
    assert names == ["Alice Smith", "Bob Jones", "Charlie Brown"]


@pytest.mark.asyncio
async def test_validate_extra_people_names_too_few_names(sample_event):
    """Test validation raises error when too few names provided."""
    modal = GatheringModal(event=sample_event)
    with pytest.raises(ValidationError) as exc_info:
        modal._validate_extra_people_names("Alice", 2)
    assert "Please provide exactly 2 non-empty name(s)" in str(exc_info.value)


@pytest.mark.asyncio
async def test_validate_extra_people_names_too_many_names(sample_event):
    """Test validation raises error when too many names provided."""
    modal = GatheringModal(event=sample_event)
    with pytest.raises(ValidationError) as exc_info:
        modal._validate_extra_people_names("Alice,Bob,Charlie", 2)
    assert "Please provide exactly 2 non-empty name(s)" in str(exc_info.value)


@pytest.mark.asyncio
async def test_validate_extra_people_names_empty_when_extras_expected(sample_event):
    """Test validation with empty string when extras are expected."""
    modal = GatheringModal(event=sample_event)
    with pytest.raises(ValidationError) as exc_info:
        modal._validate_extra_people_names("", 1)
    assert "Please provide exactly 1 name(s)" in str(exc_info.value)


@pytest.mark.asyncio
async def test_validate_extra_people_names_whitespace_when_extras_expected(sample_event):
    """Test validation with whitespace when extras are expected."""
    modal = GatheringModal(event=sample_event)
    with pytest.raises(ValidationError) as exc_info:
        modal._validate_extra_people_names("    ", 1)
    assert "Please provide exactly 1 name(s)" in str(exc_info.value)


@pytest.mark.asyncio
async def test_validate_extra_people_names_commas_only_when_extras_expected(sample_event):
    """Test validation with commas only when extras are expected."""
    modal = GatheringModal(event=sample_event)
    with pytest.raises(ValidationError) as exc_info:
        modal._validate_extra_people_names(",,,,", 2)
    assert "Please provide exactly 2 non-empty name(s)" in str(exc_info.value)


@pytest.mark.asyncio
async def test_validate_extra_people_names_trailing_comma_accepted(sample_event):
    """Test that a trailing comma is ignored, treating it as correct count."""
    modal = GatheringModal(event=sample_event)
    names = modal._validate_extra_people_names("Alice, Bob, ", 2)
    assert names == ["Alice", "Bob"]
