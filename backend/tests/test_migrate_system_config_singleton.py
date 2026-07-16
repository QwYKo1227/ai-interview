from scripts.migrate_system_config_singleton import merge_system_configs


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
