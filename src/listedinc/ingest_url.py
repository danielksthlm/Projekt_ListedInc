import argparse
import os
import sys
import hashlib
import httpx
import psycopg
import datetime as dt

try:
    import trafilatura
except Exception:
    trafilatura = None


def extract_text_and_title(html_bytes: bytes) -> tuple[str, str | None]:
    if not trafilatura:
        return html_bytes.decode("utf-8", errors="ignore"), None
    html = html_bytes.decode("utf-8", errors="ignore")
    text = trafilatura.extract(html, include_comments=False, include_links=False, favor_precision=True) or ""
    meta = trafilatura.metadata.extract_metadata(html)
    title = getattr(meta, "title", None) if meta else None
    return text.strip(), title


def main():
    ap = argparse.ArgumentParser(description="Ingest a single URL into Postgres (source + document)")
    ap.add_argument("--url", required=True)
    ap.add_argument("--insecure", action="store_true", help="Disable TLS verification (för teständamål).")
    ap.add_argument("--ca-bundle", type=str, default=None, help="Path till custom CA bundle (PEM-fil).")
    args = ap.parse_args()

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("Error: DATABASE_URL env var is required.", file=sys.stderr)
        sys.exit(1)

    url = args.url

    if args.insecure:
        verify = False
    elif args.ca_bundle:
        verify = args.ca_bundle
    else:
        verify = True

    # Fetch
    try:
        with httpx.Client(follow_redirects=True, timeout=45, verify=verify) as c:
            r = c.get(url)
    except Exception as e:
        msg = f"Fetch failed: {e}"
        if e.__class__.__name__ == "SSLError":
            msg += " (tips: prova --insecure eller ange --ca-bundle /sökväg/till/certifikat)"
        print(msg, file=sys.stderr)
        sys.exit(1)

    status = r.status_code
    content = r.content
    etag = r.headers.get("ETag")
    checksum = hashlib.sha256(content).hexdigest()

    # Classify
    is_pdf = url.lower().endswith(".pdf") or r.headers.get("Content-Type", "").lower().startswith("application/pdf")
    source_type = "pdf" if is_pdf else "html"

    # Extract text/title for HTML; leave empty for PDF (kan fyllas senare via pdfplumber)
    if not is_pdf:
        text_plain, title = extract_text_and_title(content)
    else:
        text_plain, title = "", os.path.basename(url) or "PDF"

    # Insert
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO source (company_id, url, source_type, discovered_at, last_fetched_at, http_status, etag, checksum_sha256, robots_allowed)
                VALUES (NULL, %s, %s, now(), now(), %s, %s, %s, TRUE)
                RETURNING id
                """,
                (url, source_type, status, etag, checksum),
            )
            source_id = cur.fetchone()[0]

            if is_pdf:
                cur.execute(
                    """
                    INSERT INTO document (source_id, doc_type, title, text_plain, lang, html_snapshot_url, pdf_blob_url, created_at)
                    VALUES (%s, 'report', %s, %s, NULL, NULL, %s, now())
                    RETURNING id
                    """,
                    (source_id, title or "PDF", text_plain, url),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO document (source_id, doc_type, title, text_plain, lang, html_snapshot_url, pdf_blob_url, created_at)
                    VALUES (%s, 'unknown', %s, %s, NULL, %s, NULL, now())
                    RETURNING id
                    """,
                    (source_id, title or "Untitled", text_plain, url),
                )
            document_id = cur.fetchone()[0]

    print(f"OK: source_id={source_id}, document_id={document_id}, status={status}, sha256={checksum[:12]}…")


if __name__ == "__main__":
    main()