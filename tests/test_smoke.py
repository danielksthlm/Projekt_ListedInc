def test_smoke():
    import listedinc
    # Package should have a version
    assert hasattr(listedinc, "__version__")
    v = listedinc.__version__
    assert isinstance(v, str) and len(v) > 0

    # Package should have at least one attribute/module we expect
    assert hasattr(listedinc, "ingest_url") or hasattr(listedinc, "crawl_site")


def test_database_url_env(monkeypatch):
    import os
    # Ensure DATABASE_URL is set (from .env/direnv)
    db_url = os.getenv("DATABASE_URL")
    assert db_url is not None and db_url.startswith("postgresql://")


def test_import_db_module():
    # Verify db_test module can be imported
    import listedinc.db_test as dbt
    assert dbt is not None
