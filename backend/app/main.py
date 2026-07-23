import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import auth, positions, question_banks, resumes, interviews, dashboard, coding_tests, settings, offers, offer_templates, platform, public_review, workflows, files
from app.routes.offers import router as offers_router, public_router as offers_public_router
from app.config.database import SessionLocal
from app.config.tenant_session import tenant_session
from app.models.models import User, UserRole
from app.models.tenant_models import Tenant, TenantStatus
from app.core.security import get_password_hash
from app.services.workflow_service import create_builtin_workflows
from app.core.observability import install_observability

# Seed initial user if not exists
def seed_db():
    control_db = SessionLocal()
    try:
        admin_email = os.getenv("INITIAL_ADMIN_EMAIL", "admin@example.com")
        admin_password = os.getenv("INITIAL_ADMIN_PASSWORD")
        admin_name = os.getenv("INITIAL_ADMIN_NAME", "System Admin")
        app_env = os.getenv("APP_ENV", "development")
        tenant_code = os.getenv("INITIAL_TENANT_CODE", "careray")

        if not admin_password and app_env == "development":
            admin_password = "admin123"

        tenant = (
            control_db.query(Tenant)
            .filter(
                Tenant.code == tenant_code,
                Tenant.status == TenantStatus.ACTIVE,
            )
            .first()
        )
        if tenant is None:
            print(
                f"Skipping initial admin user. Tenant {tenant_code!r} does not exist."
            )
            return
        tenant_id = tenant.id
        control_db.rollback()
        with tenant_session(tenant_id) as db:
            normalized_email = admin_email.strip().lower()
            user = db.query(User).filter(User.email == normalized_email).first()
            if not user:
                if not admin_password:
                    print("Skipping initial admin user. Set INITIAL_ADMIN_PASSWORD to seed one.")
                    return
                print("Seeding initial admin user...")
                admin_user = User(
                    email=normalized_email,
                    hashed_password=get_password_hash(admin_password),
                    full_name=admin_name,
                    role=UserRole.ADMIN
                )
                db.add(admin_user)
                db.commit()
                print(f"Admin user created: {normalized_email}")
            elif app_env == "development" and admin_password:
                user.hashed_password = get_password_hash(admin_password)
                user.full_name = user.full_name or admin_name
                user.role = UserRole.ADMIN
                db.commit()
    except Exception as e:
        print(f"Error seeding DB: {type(e).__name__}")
    finally:
        control_db.close()

seed_db()

app = FastAPI(
    title="AI Interview Assistant",
    description="API for AI Interview Assistant System",
    version="1.0.0"
)
install_observability(app)

origins = os.getenv("CORS_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(platform.router, prefix="/api")
app.include_router(positions.router, prefix="/api")
app.include_router(positions.public_router, prefix="/api")
app.include_router(question_banks.router, prefix="/api")
app.include_router(resumes.router, prefix="/api")
app.include_router(interviews.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(coding_tests.router, prefix="/api")
app.include_router(coding_tests.public_router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(offers.router, prefix="/api")
app.include_router(offers_public_router, prefix="/api")
app.include_router(offer_templates.router, prefix="/api")
app.include_router(public_review.router, prefix="/api")
app.include_router(workflows.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(files.public_router, prefix="/api")


def init_builtin_workflows_on_startup():
    control_db = SessionLocal()
    try:
        tenant_ids = [
            tenant_id
            for (tenant_id,) in control_db.query(Tenant.id)
            .filter(Tenant.status == TenantStatus.ACTIVE)
            .all()
        ]
    except Exception as e:
        print(f"Error listing tenants for builtin workflows: {type(e).__name__}")
        return
    finally:
        control_db.close()

    for tenant_id in tenant_ids:
        try:
            with tenant_session(tenant_id) as db:
                create_builtin_workflows(db)
        except Exception as e:
            print(
                "Error initializing builtin workflows for tenant "
                f"{tenant_id}: {type(e).__name__}"
            )

init_builtin_workflows_on_startup()


@app.get("/")
def read_root():
    return {"message": "Welcome to AI Interview Assistant API"}
