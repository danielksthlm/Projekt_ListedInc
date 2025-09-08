import argparse
import os
import re
import sys
import time
import itertools
import urllib.robotparser as robotparser
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

from listedinc.ingest_url import ingest_one

def _short(x) -> str:
    try:
        return str(x)[:8]
    except Exception:
        return str(x)

# Helper functions for URL scheme and www toggling
def ensure_scheme(u: str) -> str:
    # lägg till https:// om inget schema finns
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return "https://" + u


def toggle_www(u: str) -> str:
    p = urlparse(u)
    host = p.netloc or p.path  # om användaren gav bara domän utan schema
    if host.startswith("www."):
        new_host = host[4:]
    else:
        new_host = "www." + host
    if p.netloc:
        return urlunparse((p.scheme or "https", new_host, p.path, p.params, p.query, p.fragment))
    # om schema saknades ursprungligen
    return "https://" + new_host


from typing import Optional

def normalize_url(u: str, base: str | None = None) -> Optional[str]:
    """Resolve relative URL, drop fragments, normalise scheme/host, trim trailing slash (except root).
    Returns a canonical http(s) URL or None if non-http(s).
    """
    try:
        if base:
            u = urljoin(base, u)
        p = urlparse(u)
        if p.scheme not in ("http", "https"):
            return None
        netloc = (p.netloc or "").lower()
        path = p.path or "/"
        # drop fragment and keep query
        query = p.query
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        return urlunparse((p.scheme, netloc, path, "", query, ""))
    except Exception:
        return None


def unique_preserve(seq):
    seen = set(); out = []
    for x in seq:
        if not x: continue
        if x in seen: continue
        seen.add(x); out.append(x)
    return out


def build_robots(start_url: str, verify, timeout=10):
    """Return a robotparser.RobotFileParser or None if fetch fails."""
    try:
        base = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
        robots_url = urljoin(base, "/robots.txt")
        with httpx.Client(follow_redirects=True, timeout=timeout, verify=verify, headers={"User-Agent": "listedinc-crawler/0.1"}) as c:
            r = c.get(robots_url)
            if r.status_code >= 400 or not r.content:
                return None
            rp = robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.parse(r.text.splitlines())
            return rp
    except Exception:
        return None


def fetch_sitemap(start_url: str, verify, timeout=15):
    """Return a list of URLs from /sitemap.xml (best-effort), else empty list."""
    try:
        base = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
        sm_url = urljoin(base, "/sitemap.xml")
        with httpx.Client(follow_redirects=True, timeout=timeout, verify=verify, headers={"User-Agent": "listedinc-crawler/0.1"}) as c:
            r = c.get(sm_url)
            if r.status_code >= 400 or not r.content:
                return []
            try:
                root = ET.fromstring(r.content)
            except Exception:
                return []
            ns = {
                'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'
            }
            urls = []
            # urlset/loc
            for loc in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc'):
                if loc.text:
                    urls.append(loc.text.strip())
            # handle sitemap index (sitemapindex/sitemap/loc) by shallow fetch
            for sm_loc in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap/{http://www.sitemaps.org/schemas/sitemap/0.9}loc'):
                try:
                    u = sm_loc.text.strip()
                    rr = c.get(u)
                    if rr.status_code < 400 and rr.content:
                        try:
                            sub = ET.fromstring(rr.content)
                            for loc in sub.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc'):
                                if loc.text:
                                    urls.append(loc.text.strip())
                        except Exception:
                            pass
                except Exception:
                    pass
            return urls
    except Exception:
        return []

# --- auto-seed helper ---
def build_seeds(start: str) -> list[str]:
    base = f"{urlparse(start).scheme}://{urlparse(start).netloc}"
    candidates = [
        "", "/press", "/nyhet", "/nyheter", "/nyheter-och-press",
        "/pressmeddelanden", "/investerare", "/investors", "/ir",
        "/financial-reports", "/reports", "/rapporter", "/rapporter-och-presentationer",
        "/media", "/news", "/press-releases", "/annual-report",
        "/delarsrapport", "/delarsrapporter", "/arsredovisning",
        "/pdf", "/dokument", "/documents"
    ]
    out = []
    for p in candidates:
        try:
            u = normalize_url(p, base)
            if u:
                out.append(u)
        except Exception:
            pass
    return unique_preserve(out)

def hosts_from_urls(urls: list[str]) -> list[str]:
    out = []
    for u in urls:
        try:
            h = urlparse(u).netloc.lower()
            if h and h not in out:
                out.append(h)
        except Exception:
            continue
    return out

IR_HOST_RE = re.compile(r"^(invest(or|ors)?|ir|financial|finance|reports?|news|press|corporate)\.", re.I)

def discover_ir_hosts(start_url: str, verify, timeout=10) -> list[str]:
    """Heuristiskt: hämta startsida + sitemap, samla länkar, plocka värdar som ser ut som IR-domäner.
    Returnerar lista med bas-URL:er (https://host/)."""
    uniq = set()
    try:
        status, ctype, body = fetch_bytes(start_url, verify, timeout=timeout, retries=1)
    except Exception:
        body = b""
    urls = []
    if body:
        try:
            urls.extend(discover_links(start_url, body, max_links=2000))
        except Exception:
            pass
    try:
        sm = fetch_sitemap(start_url, verify, timeout=timeout)
        urls.extend(sm)
    except Exception:
        pass
    hosts = hosts_from_urls(urls)
    # egen domän utan www
    base_host = urlparse(start_url).netloc.lower()
    if base_host.startswith("www."):
        base_host = base_host[4:]
    candidates = []
    for h in hosts:
        if h == base_host or h == f"www.{base_host}":
            continue
        if IR_HOST_RE.search(h):
            candidates.append(h)
    # Håll även koll på investor.<base_host> och ir.<base_host>
    for prefix in ("investor.", "ir.", "financial."):
        candidates.append(prefix + base_host)
    out = []
    for h in unique_preserve(candidates):
        try:
            u = f"https://{h}/"
            st, _, _ = fetch_bytes(u, verify, timeout=5, retries=1)
            if st < 400:
                out.append(u)
        except Exception:
            continue
    return unique_preserve(out)

def guess_investor_subdomain(start_url: str, verify, timeout=10):
    """Return an investor.* start URL if reachable (status < 400), else None.
    Examples: https://company.se -> https://investor.company.se/
    """
    try:
        p = urlparse(start_url)
        host = p.netloc or p.path
        if not host:
            return None
        # strip www.
        if host.startswith("www."):
            host = host[4:]
        inv = f"{p.scheme or 'https'}://investor.{host}/"
        status, ctype, body = fetch_bytes(inv, verify, timeout=timeout, retries=1)
        if status and status < 400:
            return inv
    except Exception:
        return None
    return None


IR_HINTS = re.compile(r"(invest(or|ment)s?|ir|financial|reports?|press|news|media|del[aå]rs|arsredovisning|annual|interim|report)", re.I)


def same_site(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.netloc or "").split(":")[0].lower() == (pb.netloc or "").split(":")[0].lower()


def discover_links(base_url: str, html_bytes: bytes, max_links: int = 500):
    soup = BeautifulSoup(html_bytes.decode("utf-8", errors="ignore"), "lxml")
    skip_ext = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".zip", ".gz", ".tar", ".7z", ".mp4", ".mp3", ".mov")
    out = []
    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        if href.startswith("mailto:") or href.startswith("tel:"):
            continue
        nu = normalize_url(href, base_url)
        if not nu:
            continue
        low = nu.lower()
        if not low.endswith(".pdf") and any(low.endswith(ext) for ext in skip_ext):
            continue
        out.append(nu)
        if len(out) >= max_links:
            break
    return out


def fetch_bytes(url: str, verify, timeout=30, retries=3):
    last = None
    for i in range(retries):
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout, verify=verify, headers={"User-Agent": "listedinc-crawler/0.1"}) as c:
                r = c.get(url)
                return r.status_code, r.headers.get("Content-Type"), r.content
        except Exception as e:
            last = e
            time.sleep(min(1.0 * (2 ** i), 4.0))
    if last:
        raise last


def main():
    ap = argparse.ArgumentParser(description="Crawla en sajt och ingest:a sidor/PDF:er")
    ap.add_argument("--url", required=True, help="Start-URL (t.ex. https://www.kaklemax.se)")
    ap.add_argument("--max-pages", type=int, default=60, help="Max antal sidor att hämta")
    ap.add_argument("--max-depth", type=int, default=3, help="Max länkdjup (0=start-url)")
    ap.add_argument("--sleep", type=float, default=0.3, help="Paus mellan requests (sek)")
    ap.add_argument("--insecure", action="store_true", help="Disable TLS verification")
    ap.add_argument("--ca-bundle", type=str, default=None, help="Path till custom CA bundle (PEM)")
    ap.add_argument("--pdf-to-db", action="store_true", help="Lagra PDF i DB (blob_store)")
    ap.add_argument("--allow-external", action="store_true", help="Tillåt länkar utanför start-domänen")
    ap.add_argument("--use-sitemap", action="store_true", help="Försök hämta /sitemap.xml och lägg till länkar")
    ap.add_argument("--verbose", action="store_true", help="Skriv ut extra loggar (antal länkar, filtrering")
    ap.add_argument("--include", action="append", default=[], help="Regexfilter; URL måste matcha minst en för att crawlas (kan anges flera gånger)")
    ap.add_argument("--exclude", action="append", default=[], help="Regexfilter; om någon matchar så hoppas URL:en över (kan anges flera gånger)")
    ap.add_argument("--allowed-hosts", action="append", default=[], help="Tillåt enbart dessa värdnamn (regex). Kan anges flera gånger")
    ap.add_argument("--discover-ir-hosts", action="store_true", help="Upptäck IR/Investor-värdar automatiskt via länkar och sitemap")
    ap.add_argument("--ir-host-limit", type=int, default=5, help="Max antal IR-värdar att lägga till (default 5)")
    ap.add_argument("--auto-seed", action="store_true", help="Lägg till vanliga IR/press-stigar automatiskt (heuristik)")
    ap.add_argument("--seed-ignore-filters", action="store_true", help="Ignorera include/exclude-filter för auto-seedade URL:er")
    args = ap.parse_args()

    if getattr(args, "verbose", False):
        print("[ARGS]", "url=", args.url, "max_pages=", args.max_pages, "max_depth=", args.max_depth,
              "pdf_to_db=", args.pdf_to_db, "use_sitemap=", args.use_sitemap, "allow_external=", args.allow_external,
              "include=", args.include, "exclude=", args.exclude, "allowed_hosts=", args.allowed_hosts)

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("Error: DATABASE_URL saknas", file=sys.stderr); sys.exit(1)

    if args.insecure:
        verify = False
    elif args.ca_bundle:
        verify = args.ca_bundle
    else:
        verify = True

    include_res = [re.compile(p, re.I) for p in (args.include or [])]
    exclude_res = [re.compile(p, re.I) for p in (args.exclude or [])]
    allowed_host_res = [re.compile(p, re.I) for p in (args.allowed_hosts or [])]

    def passes_filters(u: str) -> bool:
        if include_res and not any(r.search(u) for r in include_res):
            return False
        if exclude_res and any(r.search(u) for r in exclude_res):
            return False
        return True

    def host_allowed(u: str) -> bool:
        if not allowed_host_res:
            return True
        try:
            h = urlparse(u).netloc
        except Exception:
            return False
        return any(r.search(h) for r in allowed_host_res)

    robots = build_robots(args.url, verify)  # kan vara None
    def allowed(u: str) -> bool:
        if robots is None:
            return True
        try:
            return robots.can_fetch("listedinc-crawler/0.1", u)
        except Exception:
            return True

    start = args.url
    start = ensure_scheme(start)
    start = normalize_url(start)
    if not start:
        print("[FAIL] Ogiltig start-URL (icke-http)", file=sys.stderr); sys.exit(1)

    # Auto-redirect to investor.<domain> if starting from main site and investor is reachable
    try:
        host = urlparse(start).netloc
        if host and not host.startswith("investor."):
            inv_url = guess_investor_subdomain(start, verify)
            if inv_url:
                if args.verbose:
                    print(f"[INFO] investor-subdomän hittad: {inv_url} (byter startpunkt)")
                start = inv_url
    except Exception:
        pass

    # Upptäck IR/Investor-värdar via länkar och sitemap
    ir_seeds = []
    if args.discover_ir_hosts:
        try:
            ir_candidates = discover_ir_hosts(start, verify)
            if args.verbose:
                print(f"[INFO] IR-värdar funna: {ir_candidates}")
            # begränsa hur många vi lägger till
            for u in ir_candidates[: max(0, args.ir_host_limit)]:
                if u != start:
                    ir_seeds.append(u)
        except Exception:
            pass

    # Initiera set/queue innan auto-seed använder dem
    seen = set()
    seen_norm = set()
    queue = [(start, 0)]
    if ir_seeds:
        queue[0:0] = [(u, 0) for u in ir_seeds]

    # Auto-seed välkända IR/press-stigar
    seeded = []
    if args.auto_seed:
        seeds = build_seeds(start)
        for u in seeds:
            if u in seen_norm:
                continue
            if (not args.allow_external) and not same_site(start, u):
                continue
            if not allowed(u):
                continue
            if not args.seed_ignore_filters and not passes_filters(u):
                continue
            seeded.append(u)
        if args.verbose:
            print(f"[INFO] auto-seed: {len(seeded)} länkar")
        queue.extend((u, 1) for u in seeded)

    # 1) Hämta och ingest:a startsidan
    try:
        status, ctype, body = fetch_bytes(start, verify)
    except Exception as e:
        # DNS-fallback: prova att toggla www.
        alt = toggle_www(start)
        if alt != start:
            try:
                status, ctype, body = fetch_bytes(alt, verify)
                print(f"[INFO] start-URL misslyckades, provar {alt} istället")
                start = alt
                queue = [(start, 0)]
            except Exception as e2:
                print(f"[FAIL] start: {start} -> {e2}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"[FAIL] start: {start} -> {e}", file=sys.stderr)
            sys.exit(1)

    try:
        sid, did, st, ch = ingest_one(dsn, start, verify, pdf_to_db=args.pdf_to_db)
        print(f"[OK d=0] {start} -> source={_short(sid)} doc={_short(did)} status={st}")
        seen.add(start)
        seen_norm.add(start)
    except Exception as e:
        print(f"[FAIL] ingest start: {start} -> {e}", file=sys.stderr)
        sys.exit(1)

    if args.verbose and not args.use_sitemap:
        print("[INFO] sitemap: hoppar över (använd --use-sitemap för att aktivera)")

    # 2a) Lägg till länkar från sitemap.xml om begärt
    if args.use_sitemap:
        sm_links = fetch_sitemap(start, verify)
        if args.verbose:
            print(f"[INFO] sitemap: hittade {len(sm_links)} länkar")
        sm_links = [normalize_url(u) for u in sm_links]
        sm_links = [u for u in sm_links if u and (args.allow_external or same_site(start, u)) and allowed(u) and passes_filters(u) and host_allowed(u)]
        # prioritera PDF först i sitemap
        sm_pdfs = [u for u in sm_links if u.lower().endswith('.pdf')]
        sm_rest = [u for u in sm_links if u not in sm_pdfs]
        queue.extend((u, 1) for u in unique_preserve(sm_pdfs + sm_rest))

    # 2) Upptäck länkar från startsidan och prioritera IR & PDF
    links = discover_links(start, body, max_links=1000)
    same = [u for u in links if (args.allow_external or same_site(start, u)) and passes_filters(u) and host_allowed(u)]
    pdfs = [u for u in same if u.lower().endswith('.pdf')]
    irish = [u for u in same if IR_HINTS.search(u) and not u.lower().endswith('.pdf')]
    rest = [u for u in same if u not in pdfs and u not in irish]
    if args.verbose:
        print(f"[INFO] html-links: total={len(same)} ir={len(irish)} pdf={len(pdfs)} rest={len(rest)}")
    # normalisera och deduplicera i prioriterad ordning
    prio = unique_preserve([normalize_url(u) for u in irish]) \
         + unique_preserve([normalize_url(u) for u in pdfs]) \
         + unique_preserve([normalize_url(u) for u in rest])
    queue = [(u, 1) for u in prio if u]

    fetched = 1
    while queue:
        u, d = queue.pop(0)
        u_norm = normalize_url(u)
        if not u_norm:
            continue
        if u_norm in seen_norm:
            continue
        if (not args.allow_external) and not same_site(start, u_norm):
            if args.verbose:
                print(f"[SKIP external] {u_norm}")
            continue
        if not allowed(u_norm):
            if args.verbose:
                print(f"[SKIP robots] {u_norm}")
            continue
        if not passes_filters(u_norm):
            if args.verbose:
                print(f"[SKIP filter] {u_norm}")
            continue
        if not host_allowed(u_norm):
            if args.verbose:
                print(f"[SKIP host] {u_norm}")
            continue
        try:
            sid, did, st, ch = ingest_one(dsn, u_norm, verify, pdf_to_db=args.pdf_to_db)
            print(f"[OK d={d}] {u_norm} -> source={_short(sid)} doc={_short(did)} status={st}")
            seen.add(u_norm)
            seen_norm.add(u_norm)
            fetched += 1
            time.sleep(args.sleep)
            if d < args.max_depth:
                try:
                    status, ctype, body = fetch_bytes(u_norm, verify)
                    links = discover_links(u_norm, body, max_links=1000)
                    # normalisera och filtrera
                    links = [normalize_url(link) for link in links]
                    links = [lnk for lnk in links if lnk and (args.allow_external or same_site(start, lnk)) and allowed(lnk) and passes_filters(lnk) and host_allowed(lnk) and lnk not in seen_norm]
                    if args.verbose:
                        print(f"[INFO d={d}] upptäckta länkar: {len(links)} (efter filter)")
                        print(f"[INFO d={d}] exempel-länkar: {links[:5]}")
                    # lägg som nästa djup
                    queue.extend((lnk, d+1) for lnk in links)
                except Exception:
                    # Ignore errors in link discovery on subpages
                    pass
        except Exception as e:
            print(f"[WARN d={d}] {u} -> {e}", file=sys.stderr)
            continue

    print(f"KLART: {fetched} sidor/objekt ingest:ade från {start}.")


if __name__ == "__main__":
    main()
