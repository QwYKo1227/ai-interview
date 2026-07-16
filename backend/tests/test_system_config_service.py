from unittest.mock import MagicMock

from app.services.system_config_service import get_or_create_system_config


def test_get_or_create_system_config_creates_the_singleton_record():
    db = MagicMock()
    db.query.return_value.filter.return_value.one_or_none.return_value = None

    config = get_or_create_system_config(db, {"llm_model": "qwen-test"})

    assert config.singleton_key is True
    assert config.llm_model == "qwen-test"
    db.add.assert_called_once_with(config)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(config)
