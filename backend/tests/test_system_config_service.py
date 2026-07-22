from app.config.tenant_session import TenantSession
from app.models.models import SystemConfig
from app.services.system_config_service import get_or_create_system_config


def test_get_or_create_system_config_creates_the_singleton_record(db, tenant_a):
    with TenantSession(bind=db.get_bind(), tenant_id=tenant_a.id) as tenant_db:
        config = get_or_create_system_config(
            tenant_db, {"llm_model": "qwen-test"}
        )

        assert config.singleton_key is True
        assert config.llm_model == "qwen-test"
        assert config.tenant_id == tenant_a.id
        assert tenant_db.query(SystemConfig).one().id == config.id
