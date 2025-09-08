import os
import sys
import hashlib
import mimetypes
import datetime as dt
import psycopg
from pathlib import Path

DATA_ROOT = Path(os.getenv("DATA_ROOT", "data")).resolve()


def sha256_file(p: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def category_for(path_under_root: Path) -> str | None:
    parts = path_under_root.parts
    return parts[0] if parts else None


def main():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("Error: DATABASE_URL env var is required.", file=sys.stderr)
        sys.exit(1)

    if not DATA_ROOT.exists():
        print(f"DATA_ROOT not found: {DATA_ROOT}", file=sys.stderr)
        sys.exit(1)

    files_seen = 0
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                "SELECT id FROM storage_location WHERE root_path=%s",
                (str(DATA_ROOT),),
            ).fetchone()
            if row:
                loc_id = row[0]
            else:
                loc_id = cur.execute(
                    "INSERT INTO storage_location(name, root_path) VALUES (%s,%s) RETURNING id",
                    ("local-raw", str(DATA_ROOT)),
                ).fetchone()[0]

            for root, _dirs, files in os.walk(DATA_ROOT):
                root_path = Path(root)
                rel_dir = root_path.relative_to(DATA_ROOT).as_posix() if root_path != DATA_ROOT else ""

                if root_path == DATA_ROOT:
                    parent_id = None
                else:
                    parent_rel = root_path.parent.relative_to(DATA_ROOT).as_posix()
                    prow = cur.execute(
                        "SELECT id FROM directory WHERE location_id=%s AND rel_path=%s",
                        (loc_id, parent_rel),
                    ).fetchone()
                    parent_id = prow[0] if prow else None

                did = cur.execute(
                    "SELECT get_or_create_directory(%s,%s,%s)",
                    (loc_id, rel_dir, parent_id),
                ).fetchone()[0]

                present_names = []
                for name in files:
                    present_names.append(name)
                    p = root_path / name
                    rel_under_root = p.relative_to(DATA_ROOT)
                    cat = category_for(rel_under_root)

                    stat = p.stat()
                    size = stat.st_size
                    mtime = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc)
                    ext = p.suffix.lower()
                    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                    sha = sha256_file(p)

                    fid = cur.execute(
                        "SELECT upsert_file_object(%s,%s,%s,%s,%s,%s,%s)",
                        (did, name, ext, size, mtime, ctype, sha),
                    ).fetchone()[0]

                    if cat in {"pdf", "html", "images", "other"}:
                        cur.execute("UPDATE file_object SET category=%s WHERE id=%s", (cat, fid))

                    files_seen += 1

                cur.execute("SELECT mark_missing_as_deleted(%s,%s)", (did, present_names))
                cur.execute("UPDATE directory SET scanned_at=now() WHERE id=%s", (did,))

    print(f"Inventory complete. Files processed: {files_seen}")


if __name__ == "__main__":
    main()