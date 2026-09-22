.PHONY: demo verify-demo reset demo-reset test backend-test frontend-test lint ai-live-demo

demo:
	bash scripts/demo.sh

verify-demo:
	bash scripts/verify-demo.sh

reset:
	docker compose up -d --wait db
	docker compose run --rm migrate
	docker compose --profile tools run --rm seed python -m afdd.seed --reset

demo-reset:
	docker compose down --volumes --remove-orphans

backend-test:
	docker compose --profile test run --build --rm test pytest -q

frontend-test:
	docker build --target test -f apps/web/Dockerfile .

test: backend-test frontend-test

ai-live-demo: verify-demo
	docker compose run --build --rm api python -m afdd.ai_demo

lint:
	docker compose --profile test run --build --rm test ruff check apps src tests db/migrations
	docker compose --profile test run --rm test python -m compileall -q apps src tests db/migrations
	docker build --target build -f apps/web/Dockerfile .
	docker compose config --quiet
	git diff --check
