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

IGNORED_DIRS = {".git", ".venv", "__pycache__", "data"}
KEY_FILES = [
    "Makefile",
    "README.md",
    ".env",
    ".envrc",
    "ruff.toml",
    "pyproject.toml",
]

SCHEMA_CANDIDATES = ["schema.sql", "db/schema.sql"]


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


def build_snapshot(root: Path, max_depth: int, no_db: bool, show_make: bool, services: bool) -> Dict[str, Any]:
    name, version, deps = read_pyproject(root)
    tree = summarize_tree(root, max_depth=max_depth)
    files = {f: (root / f).exists() for f in KEY_FILES}
    # Normalisera schema.sql – räkna som OK om någon av kandidaterna finns
    files["schema.sql"] = any((root / p).exists() for p in SCHEMA_CANDIDATES)

    dsn = os.getenv("DATABASE_URL")
    db = {"ok": False, "error": "DB-test hoppar överddes"}
    if not no_db and dsn:
        db = db_ping(dsn)
    elif not dsn:
        db = {"ok": False, "error": "DATABASE_URL not set"}

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
            "DATABASE_URL": dsn,
        },
        "database": db,
        "listedinc": import_listedinc_info(),
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
    ap.add_argument("--max-depth", type=int, default=3)
    ap.add_argument("--no-db", action="store_true")
    ap.add_argument("--show-make", action="store_true")
    ap.add_argument("--services", action="store_true")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    snap = build_snapshot(root, max_depth=args.max_depth, no_db=args.no_db, show_make=args.show_make, services=args.services)

    md = to_markdown(snap)
    Path(args.md).write_text(md, encoding="utf-8")
    Path(args.json).write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Snapshot skriven till {args.md} och {args.json}")


if __name__ == "__main__":
    main()