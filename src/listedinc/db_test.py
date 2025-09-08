import os
import psycopg
dsn = os.getenv("DATABASE_URL", "postgresql://localhost/listedinc")
with psycopg.connect(dsn) as conn:
    with conn.cursor() as cur:
        cur.execute("select now()")
        print("DB OK, now():", cur.fetchone()[0])