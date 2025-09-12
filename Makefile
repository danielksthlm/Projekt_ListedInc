.PHONY: env dev schema ingest ingest-list crawl snapshot scan test lint fmt lint-fix db-start db-stop db-restart db-status db-logs db-psql db-truncate-data db-help

# --- Service-based DB (PG17 via libpq) ---
SERVICE ?= local_listedinc_v17
PSQL_SERVICE = psql "service=$(SERVICE)" -v ON_ERROR_STOP=1

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
	$(PSQL_SERVICE) -f db/schema.sql

ingest:
	. .venv/bin/activate && PYTHONPATH=src python -m listedinc.ingest_url --url "$(URL)" $(if $(INSECURE),--insecure,) $(if $(CA_BUNDLE),--ca-bundle "$(CA_BUNDLE)",) $(if $(PDF_TO_DB),--pdf-to-db,)

ingest-list:
	. .venv/bin/activate && PYTHONPATH=src python -m listedinc.ingest_list --file "$(FILE)" $(if $(INSECURE),--insecure,) $(if $(CA_BUNDLE),--ca-bundle "$(CA_BUNDLE)",) $(if $(PDF_TO_DB),--pdf-to-db,)

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
PG_SERVICE ?= postgresql@17

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

# Öppna psql mot aktuell DB
db-psql:
	$(PSQL_SERVICE)

# Rensa all data i projektets tabeller (destruktivt)
db-truncate-data:
	@read -p "⚠️  Detta raderar ALL data i databasen '$(DB)'s ListedInc-tabeller. Fortsätt? (yes/NO) " ans; \
	if [ "$$ans" = "yes" ]; then \
	  psql -d $(DB) -f db/clear_data.sql; \
	  echo "✔️  Klart: all data rensad"; \
	else \
	  echo "Avbrutet."; \
	fi

# Service helpers (PG17)
psql-service: ; $(PSQL_SERVICE)

db-init-service: ; $(PSQL_SERVICE) -f db/schema.sql

db-clear-service:
	@test -f db/clear_data.sql && $(PSQL_SERVICE) -f db/clear_data.sql || echo "No db/clear_data.sql, skipping"

# Hjälp
db-help:
	@echo "Postgres-mål:";
	@echo "  make db-start      # starta Homebrew-tjänsten ($(PG_SERVICE))";
	@echo "  make db-stop       # stoppa tjänsten";
	@echo "  make db-restart    # starta om";
	@echo "  make db-status     # visa status";
	@echo "  make db-logs       # visa loggar";
	@echo "  Variabler: DB=$(DB), PG_SERVICE=$(PG_SERVICE) (override: make db-start PG_SERVICE=postgresql@15)";

crawl:
	@echo "[crawl] URL=$(URL) MAX_PAGES=$(MAX_PAGES) MAX_DEPTH=$(MAX_DEPTH) PDF_TO_DB=$(PDF_TO_DB) INSECURE=$(INSECURE) USE_SITEMAP=$(USE_SITEMAP) VERBOSE=$(VERBOSE) ALLOW_EXTERNAL=$(ALLOW_EXTERNAL) AUTO_SEED=$(AUTO_SEED) SEED_IGNORE_FILTERS=$(SEED_IGNORE_FILTERS) INCLUDE=$(INCLUDE) EXCLUDE=$(EXCLUDE)"
	. .venv/bin/activate && PYTHONPATH=src python -m listedinc.crawl_site --url "$(URL)" \
	$(if $(INSECURE),--insecure,) $(if $(CA_BUNDLE),--ca-bundle "$(CA_BUNDLE)",) $(if $(PDF_TO_DB),--pdf-to-db,) \
	$(if $(MAX_PAGES),--max-pages $(MAX_PAGES),) $(if $(MAX_DEPTH),--max-depth $(MAX_DEPTH),) $(if $(SLEEP),--sleep $(SLEEP),) \
	$(if $(USE_SITEMAP),--use-sitemap,) $(if $(VERBOSE),--verbose,) $(if $(ALLOW_EXTERNAL),--allow-external,) \
	$(if $(AUTO_SEED),--auto-seed,) $(if $(SEED_IGNORE_FILTERS),--seed-ignore-filters,) \
	$(foreach pat,$(INCLUDE),--include "$(pat)" ) $(foreach pat,$(EXCLUDE),--exclude "$(pat)" )

snapshot:
	. .venv/bin/activate && python PROJECT_SNAPSHOT.py --show-make --services --max-depth 3