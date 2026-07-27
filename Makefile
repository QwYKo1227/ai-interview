.PHONY: db dev-backend dev-frontend test-backend build-frontend docker-prod reset-platform-admin-password

db:
	docker compose up -d postgres

dev-backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

test-backend:
	cd backend && pytest

build-frontend:
	cd frontend && npm run build

docker-prod:
	docker compose -f docker-compose.prod.yml up --build

reset-platform-admin-password:
	@docker compose --env-file .env -f docker-compose.prod.yml build backend-migrate
	@docker compose --env-file .env -f docker-compose.prod.yml run --rm \
		backend-migrate \
		python scripts/reset_platform_admin_password.py
