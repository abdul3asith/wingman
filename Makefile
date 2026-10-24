.PHONY: install up run seed smoke reset-graph down

PY ?= python3

install:
	$(PY) -m pip install -r requirements.txt
	@test -f .env || cp .env.example .env

up:
	docker compose up -d falkordb
	@printf "waiting for FalkorDB"; until docker compose exec -T falkordb redis-cli ping 2>/dev/null | grep -q PONG; do printf "."; sleep 1; done; echo " ready"

run: up
	$(PY) -m uvicorn app.main:app --reload --port 8000

seed:
	$(PY) -m seed.load_seed

smoke:
	$(PY) scripts/smoke.py

reset-graph:
	$(PY) -c "from app.graph.db import reset; reset(); print('graph dropped')"
	$(MAKE) seed

down:
	docker compose down
