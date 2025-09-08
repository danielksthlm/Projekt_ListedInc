.PHONY: env dev schema ingest scan test lint fmt lint-fix db-start db-stop db-restart db-status db-logs db-help

PY := . .venv/bin/activate && python
PIP := . .venv/bin/activate && pip

env:
	python3 -m venv .venv ; \
	$(PIP) install -U pip ; \
	$(PIP) install -e . ; \
	$(PIP) install -e ".[dev]"

dev:
	$(PIP) install -e ".[dev]"

schema:
	psql -d listedinc -f db/schema.sql

ingest:
	. .venv/bin/activate && PYTHONPATH=src python -m listedinc.ingest_url --url "$(URL)" $(if $(INSECURE),--insecure,) $(if $(CA_BUNDLE),--ca-bundle "$(CA_BUNDLE)",)

scan:
	. .venv/bin/activate && PYTHONPATH=src python -m listedinc.inventory_scan

test:
	$(PY) -m pytest

lint:
	. .venv/bin/activate && ruff check .

fmt:
	. .venv/bin/activate && black .

lint-fix:
	. .venv/bin/activate && ruff check . --fix
	. .venv/bin/activate && black .

# -------------------------
# Postgres (Homebrew) helpers
# -------------------------
# Override with: make db-start PG_SERVICE=postgresql@15
DB ?= listedinc
PG_SERVICE ?= postgresql@16

# Start PostgreSQL via Homebrew services
db-start:
	@command -v brew >/dev/null || { echo "Homebrew saknas. Installera via https://brew.sh"; exit 1; }
	brew services start $(PG_SERVICE)
	@echo "Startar $(PG_SERVICE) ..."

# Stoppa PostgreSQL
db-stop:
	@command -v brew >/dev/null || { echo "Homebrew saknas."; exit 1; }
	brew services stop $(PG_SERVICE)
	@echo "Stoppade $(PG_SERVICE)"

# Starta om PostgreSQL
db-restart:
	@command -v brew >/dev/null || { echo "Homebrew saknas."; exit 1; }
	brew services restart $(PG_SERVICE)
	@echo "Startade om $(PG_SERVICE)"

# Status för tjänsten
db-status:
	@command -v brew >/dev/null || { echo "Homebrew saknas."; exit 1; }
	@brew services list | grep -E "^(postgresql(@[0-9]+)?)|($(PG_SERVICE))" || true
	@echo "Info:"; brew services info $(PG_SERVICE) || true

# Visa loggar (Homebrew managed)
db-logs:
	@command -v brew >/dev/null || { echo "Homebrew saknas."; exit 1; }
	@brew services log $(PG_SERVICE) || echo "Tips: kontrollera även Console.app eller /usr/local/var/log/postgres*"

# Hjälp
db-help:
	@echo "Postgres-mål:";
	@echo "  make db-start      # starta Homebrew-tjänsten ($(PG_SERVICE))";
	@echo "  make db-stop       # stoppa tjänsten";
	@echo "  make db-restart    # starta om";
	@echo "  make db-status     # visa status";
	@echo "  make db-logs       # visa loggar";
	@echo "  Variabler: DB=$(DB), PG_SERVICE=$(PG_SERVICE) (override: make db-start PG_SERVICE=postgresql@15)";

snapshot:
	. .venv/bin/activate && python PROJECT_SNAPSHOT.py --show-make --services --max-depth 3