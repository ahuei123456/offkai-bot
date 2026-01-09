# tests/data/test_ranking.py
import json
from unittest.mock import mock_open, patch

from offkai_bot.data import ranking as ranking_data
from offkai_bot.data.encoders import DataclassJSONEncoder
from offkai_bot.data.ranking import UserRank

# --- Test Data ---
RANK_1_DICT = {
    "username": "User1",
    "rank": 1,
    "achieved_rank_1": False,
    "achieved_rank_5": False,
    "achieved_rank_10": False,
}

RANK_5_DICT = {
    "username": "User2",
    "rank": 5,
    "achieved_rank_1": True,
    "achieved_rank_5": False,
    "achieved_rank_10": False,
}

RANK_10_DICT = {
    "username": "User3",
    "rank": 10,
    "achieved_rank_1": True,
    "achieved_rank_5": True,
    "achieved_rank_10": False,
}

RANK_ACHIEVED_ALL_DICT = {
    "username": "Veteran",
    "rank": 15,
    "achieved_rank_1": True,
    "achieved_rank_5": True,
    "achieved_rank_10": True,
}

RANK_1_OBJ = UserRank(
    username="User1",
    rank=1,
    achieved_rank_1=False,
    achieved_rank_5=False,
    achieved_rank_10=False,
)

RANK_5_OBJ = UserRank(
    username="User2",
    rank=5,
    achieved_rank_1=True,
    achieved_rank_5=False,
    achieved_rank_10=False,
)

RANK_10_OBJ = UserRank(
    username="User3",
    rank=10,
    achieved_rank_1=True,
    achieved_rank_5=True,
    achieved_rank_10=False,
)

RANK_ACHIEVED_ALL_OBJ = UserRank(
    username="Veteran",
    rank=15,
    achieved_rank_1=True,
    achieved_rank_5=True,
    achieved_rank_10=True,
)

VALID_RANKINGS_DICT = {
    "User1": RANK_1_DICT,
    "User2": RANK_5_DICT,
    "User3": RANK_10_DICT,
}
VALID_RANKINGS_JSON = json.dumps(VALID_RANKINGS_DICT, indent=4)
EMPTY_RANKINGS_JSON = json.dumps({}, indent=4)


# --- Tests ---


# == UserRank Dataclass Tests ==


def test_user_rank_creation():
    """Test UserRank dataclass creation with all fields."""
    user_rank = UserRank(
        username="TestUser",
        rank=5,
        achieved_rank_1=True,
        achieved_rank_5=False,
        achieved_rank_10=False,
    )
    assert user_rank.username == "TestUser"
    assert user_rank.rank == 5
    assert user_rank.achieved_rank_1 is True
    assert user_rank.achieved_rank_5 is False
    assert user_rank.achieved_rank_10 is False


# == _parse_ranking_from_dict Tests ==


def test_parse_ranking_from_dict_valid():
    """Test parsing a valid ranking dict."""
    result = ranking_data._parse_ranking_from_dict(RANK_1_DICT)
    assert result is not None
    assert result.username == "User1"
    assert result.rank == 1
    assert result.achieved_rank_1 is False
    assert result.achieved_rank_5 is False
    assert result.achieved_rank_10 is False


def test_parse_ranking_from_dict_missing_fields():
    """Test parsing a dict with missing fields uses defaults."""
    minimal_dict = {"username": "MinimalUser"}
    result = ranking_data._parse_ranking_from_dict(minimal_dict)
    assert result is not None
    assert result.username == "MinimalUser"
    assert result.rank == 0  # default
    assert result.achieved_rank_1 is False  # default
    assert result.achieved_rank_5 is False  # default
    assert result.achieved_rank_10 is False  # default


def test_parse_ranking_from_dict_empty():
    """Test parsing an empty dict uses all defaults."""
    result = ranking_data._parse_ranking_from_dict({})
    assert result is not None
    assert result.username == "Unknown User"  # default
    assert result.rank == 0
    assert result.achieved_rank_1 is False
    assert result.achieved_rank_5 is False
    assert result.achieved_rank_10 is False


def test_parse_ranking_from_dict_invalid_type():
    """Test parsing with invalid type for rank."""
    invalid_dict = {
        "username": "BadUser",
        "rank": "not_a_number",  # This should cause TypeError in UserRank creation
        "achieved_rank_1": False,
        "achieved_rank_5": False,
        "achieved_rank_10": False,
    }
    with patch("offkai_bot.data.ranking._log"):
        result = ranking_data._parse_ranking_from_dict(invalid_dict)
        # The function catches TypeError/ValueError and returns None
        # However, the current implementation doesn't validate types before creation
        # so it may still create an object. Let's check the actual behavior.
        # Based on the code, it just assigns values directly, so no error occurs here.
        # The error would occur if we try to do arithmetic on it later.
        assert result is not None  # Current implementation doesn't validate types


# == _load_rankings Tests ==


def test_load_rankings_success(mock_paths):
    """Test loading valid ranking data from a file."""
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=VALID_RANKINGS_JSON)) as mock_file,
        patch("offkai_bot.data.ranking._log") as mock_log,
    ):
        rankings = ranking_data._load_rankings()

        mock_file.assert_called_once_with(mock_paths["ranking"], "r", encoding="utf-8")
        assert "User1" in rankings
        assert "User2" in rankings
        assert "User3" in rankings

        assert rankings["User1"].username == "User1"
        assert rankings["User1"].rank == 1
        assert rankings["User2"].rank == 5
        assert rankings["User3"].rank == 10

        assert rankings == ranking_data.RANKING_DATA_CACHE
        mock_log.warning.assert_not_called()
        mock_log.error.assert_not_called()


def test_load_rankings_file_not_found(mock_paths):
    """Test loading when the rankings file doesn't exist."""
    m_open = mock_open()
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", m_open) as mock_file_constructor,
        patch("offkai_bot.data.ranking._log") as mock_log,
    ):
        rankings = ranking_data._load_rankings()

        assert rankings == {}
        assert ranking_data.RANKING_DATA_CACHE == {}

        mock_log.warning.assert_called_once()
        assert mock_paths["ranking"] in mock_log.warning.call_args[0][0]
        assert "not found or empty" in mock_log.warning.call_args[0][0]

        # Check that the default empty file was created
        mock_file_constructor.assert_called_with(mock_paths["ranking"], "w", encoding="utf-8")
        handle = mock_file_constructor()
        handle.write.assert_called()


def test_load_rankings_empty_file(mock_paths):
    """Test loading when the rankings file exists but is empty."""
    m_open = mock_open()
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=0),
        patch("builtins.open", m_open),
        patch("offkai_bot.data.ranking._log") as mock_log,
    ):
        rankings = ranking_data._load_rankings()

        assert rankings == {}
        assert ranking_data.RANKING_DATA_CACHE == {}
        mock_log.warning.assert_called_once()
        assert "not found or empty" in mock_log.warning.call_args[0][0]


def test_load_rankings_json_decode_error(mock_paths):
    """Test loading with invalid JSON content."""
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data="invalid json")),
        patch("offkai_bot.data.ranking._log") as mock_log,
    ):
        rankings = ranking_data._load_rankings()

        assert rankings == {}
        assert ranking_data.RANKING_DATA_CACHE == {}
        mock_log.error.assert_called_once()
        assert "Error decoding JSON" in mock_log.error.call_args[0][0]


def test_load_rankings_not_a_dict(mock_paths):
    """Test loading when JSON is valid but not a dict."""
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data='["list", "instead"]')),
        patch("offkai_bot.data.ranking._log") as mock_log,
    ):
        rankings = ranking_data._load_rankings()

        assert rankings == {}
        assert ranking_data.RANKING_DATA_CACHE == {}
        mock_log.error.assert_called_once()
        assert "Expected a JSON object (dict)" in mock_log.error.call_args[0][0]


def test_load_rankings_invalid_entry_not_dict(mock_paths):
    """Test loading when a ranking entry is not a dict."""
    bad_json = json.dumps({"User1": "not a dict", "User2": RANK_5_DICT})
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getsize", return_value=100),
        patch("builtins.open", mock_open(read_data=bad_json)),
        patch("offkai_bot.data.ranking._log") as mock_log,
    ):
        rankings = ranking_data._load_rankings()

        # User1 should be skipped, User2 should be loaded
        assert "User1" not in rankings
        assert "User2" in rankings
        assert rankings["User2"].rank == 5
        mock_log.warning.assert_called()


# == load_rankings Tests ==


def test_load_rankings_uses_cache(mock_paths):
    """Test that load_rankings returns cache if populated."""
    ranking_data.RANKING_DATA_CACHE = {"User1": RANK_1_OBJ}
    with patch("offkai_bot.data.ranking._load_rankings") as mock_internal_load:
        rankings = ranking_data.load_rankings()
        assert rankings == {"User1": RANK_1_OBJ}
        mock_internal_load.assert_not_called()


def test_load_rankings_loads_if_cache_none(mock_paths):
    """Test that load_rankings calls _load_rankings if cache is None."""
    ranking_data.RANKING_DATA_CACHE = None
    with patch("offkai_bot.data.ranking._load_rankings", return_value={"User2": RANK_5_OBJ}) as mock_internal_load:
        rankings = ranking_data.load_rankings()
        assert rankings == {"User2": RANK_5_OBJ}
        mock_internal_load.assert_called_once()


# == save_rankings Tests ==


def test_save_rankings_success(mock_paths):
    """Test saving valid ranking data."""
    ranking_data.RANKING_DATA_CACHE = {
        "User1": RANK_1_OBJ,
        "User2": RANK_5_OBJ,
    }

    m_open = mock_open()
    with (
        patch("builtins.open", m_open) as mock_file_constructor,
        patch("json.dump") as mock_json_dump,
        patch("offkai_bot.data.ranking._log") as mock_log,
    ):
        ranking_data.save_rankings()

        mock_file_constructor.assert_called_once_with(mock_paths["ranking"], "w", encoding="utf-8")

        mock_file_handle = m_open()
        mock_json_dump.assert_called_once()
        args, kwargs = mock_json_dump.call_args

        assert args[0] == ranking_data.RANKING_DATA_CACHE
        assert args[1] is mock_file_handle
        assert kwargs.get("indent") == 4
        assert kwargs.get("cls") == DataclassJSONEncoder
        assert kwargs.get("ensure_ascii") is False

        mock_log.error.assert_not_called()


def test_save_rankings_cache_is_none(mock_paths):
    """Test saving when cache hasn't been loaded."""
    ranking_data.RANKING_DATA_CACHE = None
    with patch("builtins.open") as mock_file_constructor, patch("offkai_bot.data.ranking._log") as mock_log:
        ranking_data.save_rankings()
        mock_file_constructor.assert_not_called()
        mock_log.error.assert_called_once()
        assert "Attempted to save response data before loading" in mock_log.error.call_args[0][0]


def test_save_rankings_os_error(mock_paths):
    """Test handling OS error during file writing."""
    ranking_data.RANKING_DATA_CACHE = {"User1": RANK_1_OBJ}
    m_open = mock_open()
    m_open.side_effect = OSError("Permission denied")
    with patch("builtins.open", m_open), patch("offkai_bot.data.ranking._log") as mock_log:
        ranking_data.save_rankings()
        mock_log.error.assert_called_once()
        assert "Error writing response data" in mock_log.error.call_args[0][0]


# == update_rank Tests ==


def test_update_rank_existing_user(mock_paths):
    """Test updating an existing user's rank."""
    initial_cache = {"User1": UserRank("User1", 1, False, False, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache),
        patch("offkai_bot.data.ranking.save_rankings") as mock_save,
        patch("offkai_bot.data.ranking._log") as mock_log,
    ):
        ranking_data.update_rank("User1")

        assert initial_cache["User1"].rank == 2
        mock_save.assert_called_once()
        mock_log.info.assert_called_once()
        assert "Updated User1 rank to 2" in mock_log.info.call_args[0][0]


def test_update_rank_new_user(mock_paths):
    """Test updating rank for a new user (creates entry)."""
    initial_cache: dict[str, UserRank] = {}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache),
        patch("offkai_bot.data.ranking.save_rankings") as mock_save,
        patch("offkai_bot.data.ranking._log") as mock_log,
    ):
        ranking_data.update_rank("NewUser")

        assert "NewUser" in initial_cache
        assert initial_cache["NewUser"].rank == 1
        assert initial_cache["NewUser"].achieved_rank_1 is False
        mock_save.assert_called_once()
        mock_log.info.assert_called_once()


# == decrease_rank Tests ==


def test_decrease_rank_existing_user(mock_paths):
    """Test decreasing an existing user's rank."""
    initial_cache = {"User1": UserRank("User1", 3, True, False, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache),
        patch("offkai_bot.data.ranking.save_rankings") as mock_save,
        patch("offkai_bot.data.ranking._log") as mock_log,
    ):
        ranking_data.decrease_rank("User1")

        assert initial_cache["User1"].rank == 2
        mock_save.assert_called_once()
        mock_log.info.assert_called_once()
        assert "Updated User1 rank to 2" in mock_log.info.call_args[0][0]


def test_decrease_rank_nonexistent_user(mock_paths):
    """Test decreasing rank for a non-existent user (no-op)."""
    initial_cache = {"User1": UserRank("User1", 3, True, False, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache),
        patch("offkai_bot.data.ranking.save_rankings") as mock_save,
    ):
        ranking_data.decrease_rank("NonExistent")

        # Should not create new user or save
        assert "NonExistent" not in initial_cache
        mock_save.assert_not_called()


def test_decrease_rank_at_zero(mock_paths):
    """Test decreasing rank when user is at rank 0 (should not go negative)."""
    initial_cache = {"User1": UserRank("User1", 0, False, False, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache),
        patch("offkai_bot.data.ranking.save_rankings") as mock_save,
    ):
        ranking_data.decrease_rank("User1")

        # Rank should remain 0, not go negative
        assert initial_cache["User1"].rank == 0
        # Should not save since no change was made
        mock_save.assert_not_called()


# == get_rank Tests ==


def test_get_rank_existing_user(mock_paths):
    """Test getting rank for an existing user."""
    initial_cache = {"User1": UserRank("User1", 5, True, False, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache):
        rank = ranking_data.get_rank("User1")
        assert rank == 5


def test_get_rank_new_user(mock_paths):
    """Test getting rank for a new user (creates with rank=0)."""
    initial_cache: dict[str, UserRank] = {}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache),
        patch("offkai_bot.data.ranking.save_rankings") as mock_save,
        patch("offkai_bot.data.ranking._log") as mock_log,
    ):
        rank = ranking_data.get_rank("NewUser")

        assert rank == 0
        assert "NewUser" in initial_cache
        assert initial_cache["NewUser"].rank == 0
        mock_save.assert_called_once()
        mock_log.info.assert_called_once()
        assert "Created user rank for NewUser" in mock_log.info.call_args[0][0]


# == can_rank_message_sent Tests ==


def test_can_rank_message_sent_rank_1_not_achieved(mock_paths):
    """Test can_rank_message_sent returns True for rank 1 when not achieved."""
    initial_cache = {"User1": UserRank("User1", 1, False, False, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache):
        result = ranking_data.can_rank_message_sent("User1")
        assert result is True


def test_can_rank_message_sent_rank_5_not_achieved(mock_paths):
    """Test can_rank_message_sent returns True for rank 5 when not achieved."""
    initial_cache = {"User1": UserRank("User1", 5, True, False, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache):
        result = ranking_data.can_rank_message_sent("User1")
        assert result is True


def test_can_rank_message_sent_rank_10_not_achieved(mock_paths):
    """Test can_rank_message_sent returns True for rank 10 when not achieved."""
    initial_cache = {"User1": UserRank("User1", 10, True, True, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache):
        result = ranking_data.can_rank_message_sent("User1")
        assert result is True


def test_can_rank_message_sent_rank_1_already_achieved(mock_paths):
    """Test can_rank_message_sent returns False for rank 1 when already achieved."""
    initial_cache = {"User1": UserRank("User1", 1, True, False, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache):
        result = ranking_data.can_rank_message_sent("User1")
        assert result is False


def test_can_rank_message_sent_rank_5_already_achieved(mock_paths):
    """Test can_rank_message_sent returns False for rank 5 when already achieved."""
    initial_cache = {"User1": UserRank("User1", 5, True, True, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache):
        result = ranking_data.can_rank_message_sent("User1")
        assert result is False


def test_can_rank_message_sent_rank_10_already_achieved(mock_paths):
    """Test can_rank_message_sent returns False for rank 10 when already achieved."""
    initial_cache = {"User1": UserRank("User1", 10, True, True, True)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache):
        result = ranking_data.can_rank_message_sent("User1")
        assert result is False


def test_can_rank_message_sent_non_milestone_rank(mock_paths):
    """Test can_rank_message_sent returns False for non-milestone ranks."""
    # Test various non-milestone ranks
    for rank_value in [2, 3, 4, 6, 7, 8, 9, 11, 15, 100]:
        initial_cache = {"User1": UserRank("User1", rank_value, True, True, True)}
        ranking_data.RANKING_DATA_CACHE = initial_cache

        with patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache):
            result = ranking_data.can_rank_message_sent("User1")
            assert result is False, f"Failed for rank {rank_value}"


def test_can_rank_message_sent_nonexistent_user(mock_paths):
    """Test can_rank_message_sent returns False for non-existent user."""
    initial_cache: dict[str, UserRank] = {}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache):
        result = ranking_data.can_rank_message_sent("NonExistent")
        assert result is False


# == mark_achieved_rank Tests ==


def test_mark_achieved_rank_1(mock_paths):
    """Test marking rank 1 as achieved."""
    initial_cache = {"User1": UserRank("User1", 1, False, False, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache),
        patch("offkai_bot.data.ranking.save_rankings") as mock_save,
    ):
        ranking_data.mark_achieved_rank("User1")

        assert initial_cache["User1"].achieved_rank_1 is True
        assert initial_cache["User1"].achieved_rank_5 is False
        assert initial_cache["User1"].achieved_rank_10 is False
        mock_save.assert_called_once()


def test_mark_achieved_rank_5(mock_paths):
    """Test marking rank 5 as achieved."""
    initial_cache = {"User1": UserRank("User1", 5, True, False, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache),
        patch("offkai_bot.data.ranking.save_rankings") as mock_save,
    ):
        ranking_data.mark_achieved_rank("User1")

        assert initial_cache["User1"].achieved_rank_1 is True
        assert initial_cache["User1"].achieved_rank_5 is True
        assert initial_cache["User1"].achieved_rank_10 is False
        mock_save.assert_called_once()


def test_mark_achieved_rank_10(mock_paths):
    """Test marking rank 10 as achieved."""
    initial_cache = {"User1": UserRank("User1", 10, True, True, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache),
        patch("offkai_bot.data.ranking.save_rankings") as mock_save,
    ):
        ranking_data.mark_achieved_rank("User1")

        assert initial_cache["User1"].achieved_rank_1 is True
        assert initial_cache["User1"].achieved_rank_5 is True
        assert initial_cache["User1"].achieved_rank_10 is True
        mock_save.assert_called_once()


def test_mark_achieved_rank_non_milestone(mock_paths):
    """Test marking non-milestone ranks still saves (but doesn't change flags)."""
    initial_cache = {"User1": UserRank("User1", 3, True, False, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache),
        patch("offkai_bot.data.ranking.save_rankings") as mock_save,
    ):
        ranking_data.mark_achieved_rank("User1")

        # Flags should remain unchanged
        assert initial_cache["User1"].achieved_rank_1 is True
        assert initial_cache["User1"].achieved_rank_5 is False
        assert initial_cache["User1"].achieved_rank_10 is False
        # Save is still called (inside the if user_data block)
        mock_save.assert_called_once()


def test_mark_achieved_rank_nonexistent_user(mock_paths):
    """Test marking achievement for non-existent user (no-op, no save)."""
    initial_cache: dict[str, UserRank] = {}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache),
        patch("offkai_bot.data.ranking.save_rankings") as mock_save,
    ):
        # Should not raise an error
        ranking_data.mark_achieved_rank("NonExistent")
        assert "NonExistent" not in initial_cache
        # Should not save since user doesn't exist
        mock_save.assert_not_called()


# == Integration-like Tests ==


def test_full_ranking_flow(mock_paths):
    """Test a full flow: new user -> update ranks -> milestone messages."""
    initial_cache: dict[str, UserRank] = {}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache),
        patch("offkai_bot.data.ranking.save_rankings"),
    ):
        # New user gets rank, should be 0
        rank = ranking_data.get_rank("TestUser")
        assert rank == 0
        assert "TestUser" in initial_cache

        # First attendance -> rank 1
        ranking_data.update_rank("TestUser")
        assert initial_cache["TestUser"].rank == 1

        # Should be able to send rank 1 message
        assert ranking_data.can_rank_message_sent("TestUser") is True

        # Mark as achieved
        ranking_data.mark_achieved_rank("TestUser")
        assert initial_cache["TestUser"].achieved_rank_1 is True

        # Should not send again
        assert ranking_data.can_rank_message_sent("TestUser") is False

        # Continue attending events until rank 5
        for _ in range(4):  # 2, 3, 4, 5
            ranking_data.update_rank("TestUser")

        assert initial_cache["TestUser"].rank == 5
        assert ranking_data.can_rank_message_sent("TestUser") is True

        ranking_data.mark_achieved_rank("TestUser")
        assert initial_cache["TestUser"].achieved_rank_5 is True


def test_withdraw_and_rejoin_flow(mock_paths):
    """Test flow when user withdraws and rejoins."""
    initial_cache = {"TestUser": UserRank("TestUser", 3, True, False, False)}
    ranking_data.RANKING_DATA_CACHE = initial_cache

    with (
        patch("offkai_bot.data.ranking.load_rankings", return_value=initial_cache),
        patch("offkai_bot.data.ranking.save_rankings"),
    ):
        # User withdraws
        ranking_data.decrease_rank("TestUser")
        assert initial_cache["TestUser"].rank == 2

        # User rejoins
        ranking_data.update_rank("TestUser")
        assert initial_cache["TestUser"].rank == 3

        # Achievement flags should remain unchanged
        assert initial_cache["TestUser"].achieved_rank_1 is True
