# PROJECT_SNAPSHOT – projekt-listedinc

Genererad: 2025-09-12T10:01:48.384300Z

## Projekt

- Namn: `projekt-listedinc`

- Version: `0.1.0`

- Python: `3.13.7`

- DATA_ROOT: `data`

- DATABASE_URL satt: `False`


### Dependencies

- psycopg[binary]>=3.2
- httpx>=0.27
- trafilatura>=1.9
- beautifulsoup4>=4.12
- lxml>=5.3
- pdfplumber>=0.11
- chardet>=5.2
- python-dotenv>=1.0
- pillow>=10.3
- pandas>=2.2
- openpyxl>=3.1


## Nyckelfiler

- ✅ Makefile
- ✅ README.md
- ✅ .env
- ✅ .envrc
- ✅ ruff.toml
- ✅ pyproject.toml
- ✅ schema.sql

## Git

- Branch: `main`
- Commit: `6d420a7`
- Ocommittade ändringar finns

## Python/Env

- Python executable: `/opt/homebrew/opt/python@3.13/bin/python3.13`
- Virtuellt miljö aktiv: `True`
- Python version: `3.13.7`

### Pip (truncated)
```
cffi==1.17.1
cryptography==45.0.7
packaging==24.2
pillow==11.3.0
projekt-listedinc==0.1.0
pybind11==3.0.1
pycparser==2.22
wheel @ file:///opt/homebrew/Cellar/python%403.13/3.13.2/libexec/wheel-0.45.1-py3-none-any.whl#sha256=b9235939e2096903717cb6bfc132267f8a7e46deb2ec3ef9c5e234ea301795d0
```
- listedinc modul: `/Users/danielkallberg/Documents/KLR_AI/Projekt_ListedInc/src/listedinc/__init__.py` version `0.1.0`

## Katalogstruktur (kort)

- .github/
- .github/workflows/
- .github/workflows/ci.yml
- db/
- db/clear_data.sql
- db/schema.sql
- docs/
- src/
- src/listedinc/
- src/listedinc/__init__.py
- src/listedinc/crawl_site.py
- src/listedinc/db_test.py
- src/listedinc/ingest_list.py
- src/listedinc/ingest_url.py
- src/listedinc/inventory_scan.py
- src/projekt_listedinc.egg-info/
- src/projekt_listedinc.egg-info/dependency_links.txt
- src/projekt_listedinc.egg-info/PKG-INFO
- src/projekt_listedinc.egg-info/requires.txt
- src/projekt_listedinc.egg-info/SOURCES.txt
- src/projekt_listedinc.egg-info/top_level.txt
- src/.DS_Store
- tests/
- tests/test_smoke.py
- tools/
- tools/run_doctor.py
- .DS_Store
- .env
- .envrc
- .gitignore
- Makefile
- PROJECT_SNAPSHOT.json
- PROJECT_SNAPSHOT.md
- PROJECT_SNAPSHOT.py
- pyproject.toml
- README.md
- requirements.txt
- ruff.toml

## Per katalog (toppnivå)
```
src: files=12, lines=1319, bytes=56152
PROJECT_SNAPSHOT.py: files=1, lines=504, bytes=16489
db: files=2, lines=357, bytes=12152
.DS_Store: files=1, lines=2, bytes=8196
README.md: files=1, lines=118, bytes=4850
Makefile: files=1, lines=122, bytes=4543
PROJECT_SNAPSHOT.json: files=1, lines=96, bytes=2567
PROJECT_SNAPSHOT.md: files=1, lines=97, bytes=1955
.envrc: files=1, lines=48, bytes=1633
tools: files=1, lines=42, bytes=1158
pyproject.toml: files=1, lines=41, bytes=801
.github: files=1, lines=40, bytes=671
.gitignore: files=1, lines=20, bytes=174
requirements.txt: files=1, lines=8, bytes=124
ruff.toml: files=1, lines=3, bytes=86
tests: files=1, lines=3, bytes=84
.env: files=1, lines=2, bytes=71
```

## Största filer
```
src/listedinc/ingest_url.py — 22524 bytes
src/listedinc/crawl_site.py — 20281 bytes
PROJECT_SNAPSHOT.py — 16489 bytes
db/schema.sql — 11763 bytes
.DS_Store — 8196 bytes
src/.DS_Store — 6148 bytes
README.md — 4850 bytes
Makefile — 4543 bytes
src/listedinc/inventory_scan.py — 3561 bytes
PROJECT_SNAPSHOT.json — 2567 bytes
```

## Senast ändrade
```
2025-09-12T10:01:43Z  PROJECT_SNAPSHOT.py
2025-09-12T09:56:38Z  tools/run_doctor.py
2025-09-12T09:44:04Z  db/schema.sql
2025-09-12T09:38:44Z  .env
2025-09-12T09:38:38Z  Makefile
2025-09-12T09:35:32Z  pyproject.toml
2025-09-12T09:26:35Z  PROJECT_SNAPSHOT.json
2025-09-12T09:26:35Z  PROJECT_SNAPSHOT.md
2025-09-08T19:50:44Z  src/listedinc/ingest_url.py
2025-09-08T19:45:02Z  src/listedinc/ingest_list.py
```

## Databas

- ❌ DB: DATABASE_URL not set
