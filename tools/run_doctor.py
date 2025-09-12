import sys
import argparse
import pathlib
import os
import psycopg

from dotenv import load_dotenv
load_dotenv()  # load .env so DATABASE_URL is available even if direnv didn't export it

# Lägg bootstrap-projektet på sys.path
sys.path.insert(0, "/Users/danielkallberg/Documents/KLR_AI/Bootstrap/klrab_bootstrap_project")

from klrab_bootstrap.doctor import run_doctor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(pathlib.Path().resolve()))
    args = ap.parse_args()
    rv = run_doctor(args.root)
    if rv is not None:
        print(rv)
    check_db()


def check_db():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL environment variable is not set.")
        return
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("select current_database(), version()")
                result = cur.fetchone()
                print(f"Database: {result[0]}, Version: {result[1]}")
    except Exception as e:
        print(f"Could not connect to the database: {e}")


if __name__ == "__main__":
    main()
