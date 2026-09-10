.PHONY: test up down logs sim

test:
	pip install -q -r requirements-dev.txt -e shared
	pytest -q

up:
	docker compose up --build -d

down:
	docker compose down -v

logs:
	docker compose logs -f gateway ingestion orchestrator alert-service

sim:
	python simulator/scenario_generator.py --name deteriorating_patient --token $(TOKEN)
