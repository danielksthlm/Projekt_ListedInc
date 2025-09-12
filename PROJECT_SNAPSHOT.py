#!/usr/bin/env python3
"""
PROJECT_SNAPSHOT.py – sammanfattar Projekt_ListedInc

Kör:
  python PROJECT_SNAPSHOT.py [--md PROJECT_SNAPSHOT.md] [--json PROJECT_SNAPSHOT.json]
                             [--max-depth 3] [--no-db] [--show-make] [--services]

Gör:
  • Läser pyproject.toml (namn, version, dependencies)
  • Sammanfattar katalogstruktur (exkl. .venv, .git, data, __pycache__)
  • Kollar nyckelfiler (schema.sql, Makefile, README.md, .env, .envrc, ruff.toml)
  • Försöker läsa Git-info (branch, senaste commit)
  • (Valfritt) Testar DB-anslutning via psycopg och DATABASE_URL + visar enkla stats
  • (Valfritt) Visar Makefile-targets
  • (Valfritt) Visar Homebrew services-status för PostgreSQL
  • Skriver både Markdown och JSON-översikt
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import tomllib  # py311+
except Exception:  # pragma: no cover
    tomllib = None

# psycopg är valfritt – snapshoten funkar även utan
try:
    import psycopg  # type: ignore
except Exception:  # pragma: no cover
    psycopg = None

# Load .env so DATABASE_URL etc. are available
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

IGNORED_DIRS = {".git", ".venv", "__pycache__", "data", ".ruff_cache", ".pytest_cache"}
KEY_FILES = [
    "Makefile",
    "README.md",
    ".env",
    ".envrc",
    "ruff.toml",
    "pyproject.toml",
]

SCHEMA_CANDIDATES = ["schema.sql", "db/schema.sql"]

# Tunables via env/flags
DEFAULT_MAX_DEPTH = 3
DEFAULT_TOPN = 10

def sha1sum(p: Path, block: int = 1024 * 1024) -> str:
    import hashlib
    h = hashlib.sha1()
    with p.open("rb") as f:
        while True:
            b = f.read(block)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def count_lines(p: Path) -> int:
    try:
        with p.open("rb") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0

def collect_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # prune ignored dirs
        base = os.path.basename(dirpath)
        if base in IGNORED_DIRS:
            dirnames[:] = []
            continue
        for d in list(dirnames):
            if d in IGNORED_DIRS:
                dirnames.remove(d)
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                if p.is_file():
                    out.append(p)
            except Exception:
                pass
    return out

def per_dir_stats(root: Path, files: list[Path]) -> list[dict]:
    buckets: dict[str, dict[str, int]] = {}
    for p in files:
        try:
            rel = p.relative_to(root)
        except Exception:
            continue
        top = rel.parts[0] if rel.parts else "."
        b = buckets.setdefault(top, {"files": 0, "bytes": 0, "lines": 0})
        b["files"] += 1
        try:
            st = p.stat()
            b["bytes"] += int(st.st_size)
            b["lines"] += count_lines(p)
        except Exception:
            pass
    out = []
    for k, v in sorted(buckets.items(), key=lambda x: (-x[1]["bytes"], x[0])):
        out.append({"path": k, **v})
    return out

def largest_files(root: Path, files: list[Path], n: int) -> list[dict]:
    sized: list[tuple[int, Path]] = []
    for p in files:
        try:
            sized.append((int(p.stat().st_size), p))
        except Exception:
            continue
    sized.sort(reverse=True, key=lambda t: t[0])
    return [{"path": str(p.relative_to(root)), "bytes": sz, "sha1": sha1sum(p)} for sz, p in sized[:n]]

def recently_modified(root: Path, files: list[Path], n: int) -> list[dict]:
    timed: list[tuple[float, Path]] = []
    for p in files:
        try:
            timed.append((p.stat().st_mtime, p))
        except Exception:
            continue
    timed.sort(reverse=True, key=lambda t: t[0])
    from datetime import datetime
    return [{"path": str(p.relative_to(root)), "mtime": datetime.utcfromtimestamp(ts).isoformat(timespec="seconds") + "Z"} for ts, p in timed[:n]]

def safe_run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
    except Exception:
        return ""

def python_info() -> dict:
    try:
        out = safe_run([sys.executable, "-m", "pip", "freeze"])[:2000]
    except Exception:
        out = ""
    return {"python": sys.version.split(" ")[0], "pip_freeze": out}

def redact_env(v: str) -> str:
    # Basic redaction for URLs of the form postgresql://user:pass@host/db
    if v.startswith("postgresql://") and "@" in v:
        try:
            prefix, rest = v.split("//", 1)
            creds, tail = rest.split("@", 1)
            return f"{prefix}//***:***@{tail}"
        except Exception:
            return v
    return v


def safe_read_text(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def read_pyproject(root: Path) -> Tuple[str | None, str | None, List[str]]:
    name = version = None
    deps: List[str] = []
    pp = root / "pyproject.toml"
    if not pp.exists() or tomllib is None:
        return name, version, deps
    try:
        data = tomllib.loads(pp.read_text(encoding="utf-8"))
        proj = data.get("project", {})
        name = proj.get("name")
        version = proj.get("version")
        deps = list(proj.get("dependencies", []) or [])
    except Exception:
        pass
    return name, version, deps


def summarize_tree(root: Path, max_depth: int = 3, max_entries: int = 50) -> List[str]:
    lines: List[str] = []

    def walk(d: Path, depth: int) -> None:
        if depth > max_depth:
            return
        rel = d.relative_to(root)
        if rel.parts and rel.parts[0] in IGNORED_DIRS:
            return
        entries = []
        try:
            entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except Exception:
            return
        shown = 0
        for p in entries:
            if p.name in IGNORED_DIRS:
                continue
            if p.is_dir():
                lines.append(f"{p.relative_to(root)}/")
                shown += 1
                if shown >= max_entries:
                    lines.append("…")
                    break
                walk(p, depth + 1)
            else:
                lines.append(str(p.relative_to(root)))
                shown += 1
                if shown >= max_entries:
                    lines.append("…")
                    break

    walk(root, 0)
    return lines


def git_info(root: Path) -> Dict[str, Any]:
    def run(args: List[str]) -> str | None:
        try:
            out = subprocess.check_output(args, cwd=root, stderr=subprocess.DEVNULL)
            return out.decode().strip()
        except Exception:
            return None

    info = {
        "branch": run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": run(["git", "rev-parse", "HEAD"]),
        "short": run(["git", "rev-parse", "--short", "HEAD"]),
        "status": run(["git", "status", "--porcelain"]),
    }
    return info


def db_ping(dsn: str) -> Dict[str, Any]:
    if psycopg is None:
        return {"ok": False, "error": "psycopg not installed"}
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("select now()")
                now = cur.fetchone()[0]
                stats = {}
                for tbl in ("source", "document", "asset", "figure"):
                    try:
                        cur.execute(f"select count(*) from {tbl}")
                        stats[tbl] = cur.fetchone()[0]
                    except Exception:
                        stats[tbl] = None
        return {"ok": True, "now": str(now), "stats": stats}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e)}


def which_python() -> str:
    return sys.executable

def venv_active() -> bool:
    # Venv heuristik
    return bool(os.environ.get("VIRTUAL_ENV")) or (hasattr(sys, "base_prefix") and sys.prefix != getattr(sys, "base_prefix", sys.prefix))

def import_listedinc_info() -> dict:
    try:
        sys.path.insert(0, str(Path(__file__).parent / "src"))  # fallback
        import listedinc  # type: ignore
        return {"ok": True, "file": getattr(listedinc, "__file__", None), "version": getattr(listedinc, "__version__", None)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

MAKE_TARGET_RE = re.compile(r"^([A-Za-z0-9_.-]+):\s*$")

def read_make_targets(root: Path) -> list[str]:
    mk = root / "Makefile"
    if not mk.exists():
        return []
    targets: list[str] = []
    try:
        for line in mk.read_text(encoding="utf-8").splitlines():
            m = MAKE_TARGET_RE.match(line.strip())
            if m:
                t = m.group(1)
                # hoppa över inbyggda/privata
                if t not in targets:
                    targets.append(t)
    except Exception:
        pass
    return targets

def brew_services_info() -> dict:
    def run(args: list[str]) -> str | None:
        try:
            out = subprocess.check_output(args, stderr=subprocess.DEVNULL)
            return out.decode().strip()
        except Exception:
            return None
    if not shutil.which("brew"):
        return {"ok": False, "error": "brew not found"}
    info = run(["brew", "services", "list"]) or ""
    lines = [line for line in info.splitlines() if "postgres" in line or "postgresql" in line]
    return {"ok": True, "list": lines}


def build_snapshot(root: Path, max_depth: int, no_db: bool, show_make: bool, services: bool, topn: int) -> Dict[str, Any]:
    name, version, deps = read_pyproject(root)
    tree = summarize_tree(root, max_depth=max_depth)
    files = {f: (root / f).exists() for f in KEY_FILES}
    # Normalisera schema.sql – räkna som OK om någon av kandidaterna finns
    files["schema.sql"] = any((root / p).exists() for p in SCHEMA_CANDIDATES)

    dsn = os.getenv("DATABASE_URL")
    db = {"ok": False, "error": "DB-test hoppades över"}
    if not no_db and dsn:
        db = db_ping(dsn)
    elif not dsn:
        db = {"ok": False, "error": "DATABASE_URL not set"}

    files_all = collect_files(root)
    by_dir = per_dir_stats(root, files_all)
    largest = largest_files(root, files_all, topn)
    recent = recently_modified(root, files_all, topn)
    pyinfo = python_info()

    snap = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "root": str(root),
        "python": sys.version.split()[0],
        "python_path": which_python(),
        "venv_active": venv_active(),
        "platform": platform.platform(),
        "project": {
            "name": name,
            "version": version,
            "dependencies": deps,
        },
        "key_files": files,
        "git": git_info(root),
        "tree": tree,
        "env": {
            "DATA_ROOT": os.getenv("DATA_ROOT"),
            "DATABASE_URL": redact_env(dsn) if dsn else None,
            "PGSERVICE": os.getenv("PGSERVICE"),
        },
        "database": db,
        "listedinc": import_listedinc_info(),
        "by_dir": by_dir,
        "largest": largest,
        "recent": recent,
        "python_info": pyinfo,
    }
    if show_make:
        snap["make_targets"] = read_make_targets(root)
    if services:
        snap["services"] = brew_services_info()
    return snap


def to_markdown(snap: Dict[str, Any]) -> str:
    proj = snap.get("project", {})
    files = snap.get("key_files", {})
    git = snap.get("git", {})

    md = []
    md.append(f"# PROJECT_SNAPSHOT – {proj.get('name') or 'Projekt_ListedInc'}\n")
    md.append(f"Genererad: {snap['generated_at']}\n")
    md.append("## Projekt\n")
    md.append(f"- Namn: `{proj.get('name')}`\n")
    md.append(f"- Version: `{proj.get('version')}`\n")
    md.append(f"- Python: `{snap['python']}`\n")
    md.append(f"- DATA_ROOT: `{(snap.get('env') or {}).get('DATA_ROOT')}`\n")
    md.append(f"- DATABASE_URL satt: `{bool((snap.get('env') or {}).get('DATABASE_URL'))}`\n")

    deps = proj.get("dependencies") or []
    if deps:
        md.append("\n### Dependencies\n")
        for d in deps:
            md.append(f"- {d}")
        md.append("")

    md.append("\n## Nyckelfiler\n")
    for k, v in files.items():
        icon = "✅" if v else "❌"
        md.append(f"- {icon} {k}")

    md.append("\n## Git\n")
    md.append(f"- Branch: `{git.get('branch')}`")
    md.append(f"- Commit: `{git.get('short')}`")
    if git.get("status"):
        md.append("- Ocommittade ändringar finns")

    md.append("\n## Python/Env\n")
    md.append(f"- Python executable: `{snap.get('python_path')}`")
    md.append(f"- Virtuellt miljö aktiv: `{snap.get('venv_active')}`")

    pyi = snap.get("python_info", {})
    if pyi:
        md.append(f"- Python version: `{pyi.get('python')}`")
        if pyi.get("pip_freeze"):
            md.append("\n### Pip (truncated)")
            md.append("```")
            md.append(pyi.get("pip_freeze"))
            md.append("```")

    listedinc = snap.get("listedinc", {})
    if listedinc.get("ok"):
        md.append(f"- listedinc modul: `{listedinc.get('file')}` version `{listedinc.get('version')}`")
    else:
        md.append(f"- listedinc modul: ❌ {listedinc.get('error')}")

    if "make_targets" in snap:
        md.append("\n## Make targets\n")
        for t in snap["make_targets"]:
            md.append(f"- {t}")

    if "services" in snap:
        md.append("\n## Homebrew services (PostgreSQL)\n")
        services = snap["services"]
        if services.get("ok"):
            if services.get("list"):
                for line in services["list"]:
                    md.append(f"- {line}")
            else:
                md.append("- Inga PostgreSQL-tjänster hittades")
        else:
            md.append(f"- Fel: {services.get('error')}")

    md.append("\n## Katalogstruktur (kort)\n")
    for line in snap.get("tree", [])[:200]:
        md.append(f"- {line}")

    md.append("\n## Per katalog (toppnivå)")
    md.append("```")
    for row in snap.get("by_dir", []) or []:
        md.append(f"{row['path']}: files={row['files']}, lines={row['lines']}, bytes={row['bytes']}")
    md.append("```")

    md.append("\n## Största filer")
    md.append("```")
    for row in snap.get("largest", []) or []:
        md.append(f"{row['path']} — {row['bytes']} bytes")
    md.append("```")

    md.append("\n## Senast ändrade")
    md.append("```")
    for row in snap.get("recent", []) or []:
        md.append(f"{row['mtime']}  {row['path']}")
    md.append("```")

    db = snap.get("database") or {}
    md.append("\n## Databas\n")
    if db.get("ok"):
        md.append(f"- ✅ Anslutning OK, now(): {db.get('now')}")
        stats = db.get("stats")
        if stats:
            md.append("- Tabellräkningar:")
            for tbl, cnt in stats.items():
                if cnt is None:
                    md.append(f"  - {tbl}: ❌ kunde inte läsa")
                else:
                    md.append(f"  - {tbl}: {cnt}")
    else:
        md.append(f"- ❌ DB: {db.get('error')}")

    md.append("")
    return "\n".join(md)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="PROJECT_SNAPSHOT.md")
    ap.add_argument("--json", default="PROJECT_SNAPSHOT.json")
    ap.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    ap.add_argument("--topn", type=int, default=DEFAULT_TOPN)
    ap.add_argument("--no-db", action="store_true")
    ap.add_argument("--show-make", action="store_true")
    ap.add_argument("--services", action="store_true")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    topn = args.topn
    snap = build_snapshot(root, max_depth=args.max_depth, no_db=args.no_db, show_make=args.show_make, services=args.services, topn=topn)

    md = to_markdown(snap)
    Path(args.md).write_text(md, encoding="utf-8")
    Path(args.json).write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Snapshot skriven till {args.md} och {args.json}")


if __name__ == "__main__":
    main()