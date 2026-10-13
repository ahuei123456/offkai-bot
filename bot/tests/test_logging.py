import logging

import pytest

from offkai_bot.main import configure_logging


@pytest.fixture(autouse=True)
def restore_root_logging():
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    original_level = root_logger.level

    yield

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        if handler not in original_handlers:
            handler.close()
    for handler in original_handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(original_level)


def test_configure_logging_writes_to_file(tmp_path):
    log_file = tmp_path / "logs" / "offkai-bot.log"

    configure_logging(str(log_file))
    logging.getLogger("offkai_bot.test").info("test log message")

    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_file.exists()
    assert "test log message" in log_file.read_text(encoding="utf-8")


def test_configure_logging_can_run_without_file(tmp_path):
    log_file = tmp_path / "logs" / "offkai-bot.log"

    configure_logging(log_file=None)
    logging.getLogger("offkai_bot.test").info("console only")

    assert not log_file.exists()
