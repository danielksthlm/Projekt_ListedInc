import argparse
import csv
import os
import sys
from pathlib import Path

from listedinc.ingest_url import ingest_one

def main():
    ap = argparse.ArgumentParser(description="Ingest flera URL:er från CSV")
    ap.add_argument("--file", required=True, help="CSV med header: url (eller name,url)")
    ap.add_argument("--insecure", action="store_true", help="Disable TLS verification")
    ap.add_argument("--ca-bundle", type=str, default=None, help="Path till custom CA bundle (PEM)")
    ap.add_argument("--pdf-to-db", action="store_true", help="Lagra PDF i DB (blob_store)")
    args = ap.parse_args()

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("Error: DATABASE_URL saknas", file=sys.stderr)
        sys.exit(1)

    if args.insecure:
        verify = False
    elif args.ca_bundle:
        verify = args.ca_bundle
    else:
        verify = True

    p = Path(args.file)
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        sys.exit(1)

    total = ok = 0
    with p.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        # hitta url-kolumn
        try:
            if header and any(h.lower() == "url" for h in header):
                url_idx = [i for i,h in enumerate(header) if h.lower()=="url"][0]
            else:
                # ingen header -> behandla första raden som data
                f.seek(0)
                reader = csv.reader(f)
                url_idx = 0
        except Exception:
            url_idx = 0

        for row in reader:
            if not row or len(row) <= url_idx:
                continue
            url = row[url_idx].strip()
            if not url:
                continue
            total += 1
            try:
                sid, did, status, checksum = ingest_one(dsn, url, verify, pdf_to_db=args.pdf_to_db)
                ok += 1
                print(f"[OK] {url} -> source={sid[:8]} doc={did[:8]} status={status} sha={checksum[:12]}…")
            except Exception as e:
                print(f"[FAIL] {url} -> {e}", file=sys.stderr)

    print(f"KLART: {ok}/{total} URL:er ingested.")

if __name__ == "__main__":
    main()