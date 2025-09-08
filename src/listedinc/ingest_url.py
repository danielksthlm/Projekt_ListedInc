import argparse
import os
import sys
import hashlib
import httpx
import psycopg
import json
import re
from bs4 import BeautifulSoup
import dateparser
from io import BytesIO
from urllib.parse import urlparse

try:
    import trafilatura
except Exception:
    trafilatura = None


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:(?:\+46|0)\s?\d{1,3}(?:[\s-]?\d{2,3}){2,4})")


ROLE_HINTS = re.compile(r"\b(VD|CEO|CFO|IR|IR-?chef|IR-?kontakt|Investerarrelationer|Finanschef|Kommunikationschef)\b", re.I)

# Regex for Swedish/Titlecase names
NAME_CAND_RE = re.compile(r"\b[A-ZÅÄÖ][a-zåäö\-]+(?:\s+[A-ZÅÄÖ][a-zåäö\-]+){1,3}\b")

# Helpers: normalize Swedish phone formats
def _normalize_phone(p: str) -> str:
    raw = p.strip()
    digits = re.sub(r"\D", "", raw)
    # normalize +46.. to 0..
    if digits.startswith("46") and not digits.startswith("460"):
        digits = "0" + digits[2:]
    # common Swedish lengths: 9–11 digits starting with 0
    if not digits.startswith("0") or len(digits) < 8 or len(digits) > 11:
        return raw
    # Mobile 07x-xxx xx xx
    if digits.startswith("07") and len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]} {digits[6:8]} {digits[8:10]}"
    # Stockholm 08-xxx xx xx (9 or 10 digits incl leading 0)
    if digits.startswith("08") and len(digits) in (9, 10):
        rest = digits[2:]
        return f"08-{rest[:3]} {rest[3:5]} {rest[5:7]}".strip()
    # Generic 0xx-xxx xx xx
    if len(digits) >= 10:
        return f"{digits[:3]}-{digits[3:6]} {digits[6:8]} {digits[8:10]}".strip()
    # Fallback keep raw if unusual
    return raw


def _normalize_phone_set(phones: set[str]) -> list[str]:
    normed = {_normalize_phone(p) for p in phones}
    return sorted(normed)

# DOM helper functions for contextual people extraction
def _collect_near_text(el, max_chars: int = 400) -> str:
    """Collect text around an element: parent + prev/next siblings, limited length."""
    parts = []
    try:
        if el.parent:
            parts.append(el.parent.get_text(" ", strip=True))
        # previous siblings
        prev = []
        sib = el.previous_sibling
        k = 0
        while sib is not None and k < 3:
            if hasattr(sib, 'get_text'):
                prev.append(sib.get_text(" ", strip=True))
            elif isinstance(sib, str):
                prev.append(sib.strip())
            sib = sib.previous_sibling
            k += 1
        # next siblings
        nxt = []
        sib = el.next_sibling
        k = 0
        while sib is not None and k < 3:
            if hasattr(sib, 'get_text'):
                nxt.append(sib.get_text(" ", strip=True))
            elif isinstance(sib, str):
                nxt.append(sib.strip())
            sib = sib.next_sibling
            k += 1
        parts = prev[::-1] + parts + nxt
        txt = " ".join([p for p in parts if p])
        return txt[:max_chars]
    except Exception:
        return ""

def _guess_name(text: str) -> str | None:
    m = NAME_CAND_RE.search(text)
    return m.group(0) if m else None

def _guess_role(text: str) -> str | None:
    m = ROLE_HINTS.search(text)
    return m.group(0) if m else None

def _extract_people_from_dom(soup: BeautifulSoup) -> list[dict]:
    people: dict[str, dict] = {}
    # mailto anchors
    for a in soup.find_all('a', href=True):
        href = (a.get('href') or '').strip().lower()
        if href.startswith('mailto:'):
            em = href.split(':',1)[1].split('?',1)[0]
            ctx = _collect_near_text(a)
            name = _guess_name(ctx)
            role = _guess_role(ctx)
            ph_match = PHONE_RE.search(ctx)
            entry = people.get(em, {"email": em})
            if name and not entry.get("name"):
                entry["name"] = name
            if role and not entry.get("role"):
                entry["role"] = role
            if ph_match and not entry.get("phone"):
                entry["phone"] = _normalize_phone(ph_match.group(0))
            people[em] = entry
    # cloudflare elements
    for el in soup.select('[data-cfemail]'):
        dec = _cf_decode_email(el.get('data-cfemail','') or '')
        if not dec:
            continue
        ctx = _collect_near_text(el)
        name = _guess_name(ctx)
        role = _guess_role(ctx)
        ph_match = PHONE_RE.search(ctx)
        entry = people.get(dec, {"email": dec})
        if name and not entry.get("name"):
            entry["name"] = name
        if role and not entry.get("role"):
            entry["role"] = role
        if ph_match and not entry.get("phone"):
            entry["phone"] = _normalize_phone(ph_match.group(0))
        people[dec] = entry
    return list(people.values())

# Helper: decode Cloudflare email protection
def _cf_decode_email(hexstr: str) -> str | None:
    try:
        data = bytes.fromhex(hexstr)
        key = data[0]
        return ''.join(chr(b ^ key) for b in data[1:])
    except Exception:
        return None

# Helper: extract/validate phones from text
def _extract_phones_from_text(text: str) -> set[str]:
    cands = set(m.group(0).strip() for m in PHONE_RE.finditer(text))
    out: set[str] = set()
    for p in cands:
        digits = re.sub(r'\D', '', p)
        if digits.startswith('46') and not digits.startswith('460'):
            digits = '0' + digits[2:]
        if 8 <= len(digits) <= 11 and re.search(r'[1-9]', digits):
            out.add(p)
    return set(_normalize_phone_set(out))

def extract_html_metadata(html_bytes: bytes) -> dict:
    html = html_bytes.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")

    # Headings
    h1 = [h.get_text(strip=True) for h in soup.find_all("h1")]
    h2 = [h.get_text(strip=True) for h in soup.find_all("h2")]
    headings = [t for t in (h1 + h2) if t]

    # Published time candidates
    published_at = None
    # <meta property="article:published_time" content="...">
    meta_pt = soup.find("meta", attrs={"property": "article:published_time"})
    if meta_pt and meta_pt.get("content"):
        published_at = dateparser.parse(meta_pt["content"], settings={"RETURN_AS_TIMEZONE_AWARE": True})
    if not published_at:
        meta_date = soup.find("meta", attrs={"name": re.compile(r"date|pub|publish", re.I)})
        if meta_date and meta_date.get("content"):
            published_at = dateparser.parse(meta_date["content"], settings={"RETURN_AS_TIMEZONE_AWARE": True})
    if not published_at:
        t = soup.find("time")
        if t and (t.get("datetime") or t.get_text(strip=True)):
            published_at = dateparser.parse(t.get("datetime") or t.get_text(strip=True), settings={"RETURN_AS_TIMEZONE_AWARE": True})

    # Tags / keywords
    tags = []
    meta_kw = soup.find("meta", attrs={"name": re.compile(r"keywords|tags", re.I)})
    if meta_kw and meta_kw.get("content"):
        for token in re.split(r",|;|\|", meta_kw["content"]):
            token = token.strip()
            if token:
                tags.append(token)
    for a in soup.find_all("a", rel=lambda v: v and "tag" in v):
        txt = a.get_text(strip=True)
        if txt:
            tags.append(txt)
    tags = list(dict.fromkeys(tags))  # dedupe, preserve order

    # Contacts: emails via mailto and visible text
    emails = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            addr = href.split(":", 1)[1].split("?", 1)[0]
            if addr:
                emails.add(addr)
    # also scan text quickly
    for m in EMAIL_RE.finditer(html):
        emails.add(m.group(0))
    # Cloudflare email protection (data-cfemail)
    for el in soup.select('[data-cfemail]'):
        dec = _cf_decode_email(el.get('data-cfemail', ''))
        if dec:
            emails.add(dec)

    # Phones from visible text (validated)
    visible_text = soup.get_text("\n")
    phones = _extract_phones_from_text(visible_text)

    # DOM-based people extraction around email elements
    dom_people = _extract_people_from_dom(soup)

    # Heuristic: build simple people list based on lines around emails
    people = []
    lines = [ln.strip() for ln in visible_text.splitlines()]
    # Build a quick index of line -> email hits
    email_to_idx = {}
    for idx, ln in enumerate(lines):
        for em in EMAIL_RE.findall(ln):
            email_to_idx.setdefault(em, idx)
    for em, idx in email_to_idx.items():
        name = None
        role = None
        # look up to 3 lines above for a name-like line
        for j in range(max(0, idx-3), idx):
            cand = lines[j].strip()
            if 2 <= cand.count(" ") <= 4 and cand.istitle():
                name = cand
        # also consider immediate previous non-empty line
        k = idx-1
        while k >= 0 and not lines[k].strip():
            k -= 1
        if k >= 0 and not name:
            prev = lines[k].strip()
            # prefer two-token proper names
            if len(prev.split()) in (2,3):
                name = prev
        # role below (or above) with role hints
        for j in (idx+1, idx+2, idx-1):
            if 0 <= j < len(lines):
                if ROLE_HINTS.search(lines[j]):
                    role = lines[j].strip()
                    break
        entry = {"email": em}
        if name:
            entry["name"] = name
        if role:
            entry["role"] = role
        people.append(entry)

    # Merge DOM-based people with line-heuristic
    merged: dict[str, dict] = {}
    for p in dom_people + people:
        em = (p.get("email") or "").strip().lower()
        if not em:
            continue
        cur = merged.get(em, {})
        # prefer entries that have name/role
        if not cur:
            merged[em] = p
        else:
            if not cur.get("name") and p.get("name"):
                cur["name"] = p["name"]
            if not cur.get("role") and p.get("role"):
                cur["role"] = p["role"]
            if not cur.get("phone") and p.get("phone"):
                cur["phone"] = p["phone"]
            merged[em] = cur
    people = list(merged.values())

    # Merge contacts payload
    contacts_payload = {"emails": sorted(emails)}
    if phones:
        contacts_payload["phones"] = sorted(phones)
    if people:
        contacts_payload["people"] = people

    # JSON-LD (schema.org)
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(node.string or "{}")
            objs = data if isinstance(data, list) else [data]
            for obj in objs:
                if not isinstance(obj, dict):
                    continue
                if not published_at:
                    for k in ("datePublished", "dateCreated", "dateModified"):
                        if obj.get(k):
                            parsed = dateparser.parse(str(obj[k]), settings={"RETURN_AS_TIMEZONE_AWARE": True})
                            if parsed:
                                published_at = parsed
                                break
                kws = obj.get("keywords")
                if isinstance(kws, list):
                    tags.extend([str(x).strip() for x in kws if str(x).strip()])
                elif isinstance(kws, str):
                    for token in re.split(r",|;|\|", kws):
                        token = token.strip()
                        if token:
                            tags.append(token)
        except Exception:
            continue

    # Final fallback: search visible text for Swedish long dates or numeric dates
    if not published_at and visible_text:
        m = DATE_TEXT_SV_RE.search(visible_text)
        if m:
            published_at = dateparser.parse(
                m.group(1),
                settings={"RETURN_AS_TIMEZONE_AWARE": True, "PREFER_DAY_OF_MONTH": "first"}
            )
        if not published_at:
            m2 = DATE_CAND_RE.search(visible_text)
            if m2:
                published_at = _try_parse_date(m2.group(1))

    payload = {
        "headings": headings,
        "published_at": published_at.isoformat() if published_at else None,
        "tags": tags,
        "contacts": contacts_payload,
    }
    return payload


def extract_text_and_title(html_bytes: bytes) -> tuple[str, str | None]:
    if not trafilatura:
        return html_bytes.decode("utf-8", errors="ignore"), None
    html = html_bytes.decode("utf-8", errors="ignore")
    text = trafilatura.extract(html, include_comments=False, include_links=False, favor_precision=True) or ""
    meta = trafilatura.metadata.extract_metadata(html)
    title = getattr(meta, "title", None) if meta else None
    return text.strip(), title

DATE_CAND_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{2}[\./-]\d{2}[\./-]\d{4})\b")

MONTHS_SV = r"januari|februari|mars|april|maj|juni|juli|augusti|september|oktober|november|december"
DATE_TEXT_SV_RE = re.compile(rf"\b(\d{{1,2}}\s+(?:{MONTHS_SV})\s+\d{{4}})\b", re.I)

def _try_parse_date(val: str):
    if not val:
        return None
    try:
        return dateparser.parse(val, settings={"RETURN_AS_TIMEZONE_AWARE": True})
    except Exception:
        return None

def _parse_pdf_datetime(pdf_dt: str):
    # PDF dates often like D:YYYYMMDDHHmmSS+TZ
    try:
        m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", pdf_dt)
        if not m:
            return None
        y, mo, d, hh, mm, ss = m.groups()
        mo = mo or '01'
        d = d or '01'
        hh = hh or '00'
        mm = mm or '00'
        ss = ss or '00'
        iso = f"{y}-{mo}-{d} {hh}:{mm}:{ss}"
        return dateparser.parse(iso, settings={"RETURN_AS_TIMEZONE_AWARE": True})
    except Exception:
        return None

def extract_pdf_text_and_date(content: bytes, url: str) -> tuple[str, str | None]:
    text = ""
    dt_found = None
    try:
        import pdfplumber
        with pdfplumber.open(BytesIO(content)) as pdf:
            # metadata date
            try:
                meta = pdf.metadata or {}
                for key in ("CreationDate", "ModDate", "creationDate", "modDate"):
                    if key in meta and not dt_found:
                        dt_found = _parse_pdf_datetime(str(meta[key]))
            except Exception:
                pass
            # text (first 2 pages for speed)
            pages = pdf.pages[:2] if len(pdf.pages) > 2 else pdf.pages
            chunks = []
            for p in pages:
                t = p.extract_text() or ""
                if t:
                    chunks.append(t)
            text = "\n\n".join(chunks).strip()
            # search dates in text if still missing
            if not dt_found and text:
                m = DATE_CAND_RE.search(text)
                if m:
                    dt_found = _try_parse_date(m.group(0))
    except Exception:
        pass
    # filename date as fallback
    if not dt_found and url:
        fname = os.path.basename(urlparse(url).path)
        m = DATE_CAND_RE.search(fname)
        if m:
            dt_found = _try_parse_date(m.group(0))
    return text, (dt_found.isoformat() if dt_found else None)


def store_blob(conn, data: bytes, content_type: str) -> str:
    """Store bytes in blob_store with checksum dedupe. Return blob id (UUID)."""
    sha = hashlib.sha256(data).hexdigest()
    with conn.cursor() as cur:
        row = cur.execute(
            "SELECT id FROM blob_store WHERE checksum_sha256=%s",
            (sha,),
        ).fetchone()
        if row:
            return row[0]
        row = cur.execute(
            """
            INSERT INTO blob_store (content_type, content_length, checksum_sha256, data)
            VALUES (%s,%s,%s,%s)
            RETURNING id
            """,
            (content_type, len(data), sha, psycopg.Binary(data)),
        ).fetchone()
        return row[0]


def ingest_one(dsn: str, url: str, verify, pdf_to_db: bool=False) -> tuple[str, str, int, str]:
    # Fetch
    with httpx.Client(follow_redirects=True, timeout=45, verify=verify) as c:
        r = c.get(url)
    status = r.status_code
    content = r.content
    etag = r.headers.get("ETag")
    checksum = hashlib.sha256(content).hexdigest()

    # Classify
    is_pdf = url.lower().endswith(".pdf") or r.headers.get("Content-Type", "").lower().startswith("application/pdf")
    source_type = "pdf" if is_pdf else "html"

    # Extract for HTML
    if not is_pdf:
        text_plain, title = extract_text_and_title(content)
        rich = extract_html_metadata(content)
        headings_json = json.dumps(rich.get("headings", []))
        tags_json = json.dumps(rich.get("tags", []))
        contacts_json = json.dumps(rich.get("contacts", {}))
        published_at_val = rich.get("published_at")
    else:
        text_plain, title = "", os.path.basename(url) or "PDF"
        headings_json = json.dumps([])
        tags_json = json.dumps([])
        contacts_json = json.dumps({})
        published_at_val = None

        # PDF text + date extraction
        pdf_text, pdf_dt_iso = extract_pdf_text_and_date(content, url)
        if pdf_text:
            text_plain = pdf_text
        if (not published_at_val) and pdf_dt_iso:
            published_at_val = pdf_dt_iso

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            # 0) Finns source redan för denna URL?
            cur.execute(
                "SELECT id, checksum_sha256 FROM source WHERE url=%s ORDER BY discovered_at DESC LIMIT 1",
                (url,),
            )
            row = cur.fetchone()
            source_id = None

            if row:
                existing_source_id, prev_sha = row
                if prev_sha == checksum:
                    # Inget nytt: uppdatera metadata och återanvänd senaste dokumentet om det finns
                    cur.execute(
                        "UPDATE source SET http_status=%s, etag=%s, last_fetched_at=now() WHERE id=%s",
                        (status, etag, existing_source_id),
                    )
                    cur.execute(
                        "SELECT id FROM document WHERE source_id=%s ORDER BY created_at DESC LIMIT 1",
                        (existing_source_id,),
                    )
                    drow = cur.fetchone()
                    existing_doc_id = drow[0] if drow else None
                    return existing_source_id, (existing_doc_id or ""), status, checksum
                else:
                    # Innehållet har ändrats: uppdatera befintlig source-rad och fortsätt skapa nytt dokument
                    cur.execute(
                        "UPDATE source SET checksum_sha256=%s, http_status=%s, etag=%s, last_fetched_at=now() WHERE id=%s",
                        (checksum, status, etag, existing_source_id),
                    )
                    source_id = existing_source_id
            else:
                # Ny källa
                cur.execute(
                    """
                    INSERT INTO source (company_id, url, source_type, discovered_at, last_fetched_at, http_status, etag, checksum_sha256, robots_allowed)
                    VALUES (NULL, %s, %s, now(), now(), %s, %s, %s, TRUE)
                    RETURNING id
                    """,
                    (url, source_type, status, etag, checksum),
                )
                source_id = cur.fetchone()[0]

            # 1) Skapa nytt dokument (förändrat eller ny URL)
            if is_pdf:
                cur.execute(
                    """
                    INSERT INTO document (source_id, doc_type, title, text_plain, lang,
                                           html_snapshot_url, pdf_blob_url, created_at,
                                           published_at, headings, contacts, tags, checksum_sha256)
                    VALUES (%s, 'report', %s, %s, NULL, NULL, %s, now(), %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (source_id, title or "PDF", text_plain, url,
                     published_at_val, headings_json, contacts_json, tags_json, checksum),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO document (source_id, doc_type, title, text_plain, lang,
                                           html_snapshot_url, pdf_blob_url, created_at,
                                           published_at, headings, contacts, tags, checksum_sha256)
                    VALUES (%s, 'unknown', %s, %s, NULL, %s, NULL, now(), %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (source_id, title or "Untitled", text_plain, url,
                     published_at_val, headings_json, contacts_json, tags_json, checksum),
                )
            document_id = cur.fetchone()[0]

            # 2) Spara original-PDF i DB om flaggat
            if is_pdf and pdf_to_db:
                blob_id = store_blob(conn, content, r.headers.get("Content-Type", "application/pdf"))
                cur.execute("UPDATE document SET blob_id=%s WHERE id=%s", (blob_id, document_id))

    return source_id, document_id, status, checksum


def main():
    ap = argparse.ArgumentParser(description="Ingest a single URL into Postgres (source + document)")
    ap.add_argument("--url", required=True)
    ap.add_argument("--insecure", action="store_true", help="Disable TLS verification (för teständamål).")
    ap.add_argument("--ca-bundle", type=str, default=None, help="Path till custom CA bundle (PEM-fil).")
    ap.add_argument("--pdf-to-db", action="store_true", help="Lagra original-PDF i databasen (blob_store).")
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

    try:
        sid, did, status, checksum = ingest_one(dsn, url, verify, pdf_to_db=args.pdf_to_db)
    except Exception as e:
        msg = f"Fetch failed: {e}"
        if e.__class__.__name__ == "SSLError":
            msg += " (tips: prova --insecure eller ange --ca-bundle /sökväg/till/certifikat)"
        print(msg, file=sys.stderr)
        sys.exit(1)

    print(f"OK: source_id={sid}, document_id={did}, status={status}, sha256={checksum[:12]}…")


if __name__ == "__main__":
    main()