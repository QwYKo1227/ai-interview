import pytest

from scripts.migrate_system_config_singleton import (
    TARGET_ALEMBIC_VERSION,
    merge_system_configs,
    target_alembic_version,
)


def test_merge_system_configs_keeps_newest_record_and_fills_empty_values():
    newest = {
        "id": "newest",
        "smtp_host": "",
        "mail_enabled": False,
        "prompt_configs": {},
    }
    older = {
        "id": "older",
        "smtp_host": "smtp.example.com",
        "mail_enabled": True,
        "prompt_configs": {"generate_jd": {"system": "test"}},
    }

    canonical, duplicate_ids = merge_system_configs([newest, older])

    assert canonical["id"] == "newest"
    assert canonical["smtp_host"] == "smtp.example.com"
    assert canonical["mail_enabled"] is False
    assert canonical["prompt_configs"] == older["prompt_configs"]
    assert duplicate_ids == ["older"]


def test_target_alembic_version_marks_only_the_known_predecessor():
    assert target_alembic_version(None) is None
    assert target_alembic_version("j9k0l1m2n3o4") == TARGET_ALEMBIC_VERSION
    assert target_alembic_version(TARGET_ALEMBIC_VERSION) == TARGET_ALEMBIC_VERSION

    with pytest.raises(RuntimeError, match="未知"):
        target_alembic_version("unexpected-version")
