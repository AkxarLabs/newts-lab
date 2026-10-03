"""Create a new, empty lab from this template — what the dashboard's "Create a new lab" does.

    uv run --with pyyaml python tools/new_lab.py <dest> [--name "My lab"] [--projects-root ../my-lab-projects]

Copies this hub's committed files (`git archive HEAD`, so nothing uncommitted, ignored or runtime comes
along), drops the template's own notebook entries, names the lab (`lab.name`), points
`lab.projects_root` at its own sibling folder, then `git init` + a first commit. The result is exactly
what "Use this template" on GitHub gives you, ready for /setup-lab.
"""

from __future__ import annotations

import argparse
import io
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
SKIP_TOP = {".github"}                      # the template's own CI is not the new lab's
EMPTY_ROW = "| — | *(empty — run `/ideate` to start)* | | | | | | |"
EMPTY_KNOWLEDGE = {"FAILURES.md": "*(no failures recorded yet)*", "FINDINGS.md": "*(no findings yet)*",
                   "OPEN-QUESTIONS.md": "*(no open questions yet)*", "REFERENCES.md": "*(no references yet)*"}


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, timeout=120)


def _export(template: Path, dest: Path) -> int:
    """Write the template's committed tree into dest. Falls back to a filtered copy when the template
    is not a git checkout (e.g. a downloaded zip)."""
    n = 0
    if shutil.which("git") and (template / ".git").exists():
        r = _git(["archive", "--format=tar", "HEAD"], template)
        if r.returncode == 0:
            with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
                for mem in tf.getmembers():
                    top = mem.name.split("/", 1)[0]
                    if top in SKIP_TOP or mem.name.startswith(("/", "..")) or ".." in Path(mem.name).parts:
                        continue
                    tf.extract(mem, dest, filter="data") if hasattr(tarfile, "data_filter") else tf.extract(mem, dest)
                    n += 1
            return n
    ignore = shutil.ignore_patterns(".git", ".bus", ".slots", "__pycache__", ".pytmp", ".pytest_cache", ".venv",
                                    "site", "assets-src", "*.pyc", ".env.local")
    for item in template.iterdir():
        if item.name in SKIP_TOP or item.name in (".git", "site", ".venv", ".pytmp", ".pytest_cache"):
            continue
        if item.is_dir():
            shutil.copytree(item, dest / item.name, ignore=ignore)
        else:
            shutil.copy2(item, dest / item.name)
        n += 1
    return n


def _reset_state(dest: Path) -> None:
    nb = dest / "lab" / "notebook"
    for f in nb.glob("*.md") if nb.is_dir() else []:
        if f.name != "README.md":
            f.unlink()
    for d in ("lab/.bus", "lab/.slots", "lab/campaigns"):
        shutil.rmtree(dest / d, ignore_errors=True)
    for d in (dest / "studies").iterdir() if (dest / "studies").is_dir() else []:
        if d.is_dir():
            shutil.rmtree(d)
    # the template may itself be someone's working lab: empty the registry table and knowledge base
    reg = dest / "lab" / "REGISTRY.md"
    if reg.exists():
        text = reg.read_text(encoding="utf-8-sig")
        text = re.sub(r"(\|[-| ]+\|\n)(?:\|.*\|\n)+", lambda m: m.group(1) + EMPTY_ROW + "\n", text, count=1)
        reg.write_text(text, encoding="utf-8", newline="")
    for fname, empty in EMPTY_KNOWLEDGE.items():
        f = dest / "lab" / "knowledge" / fname
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8-sig")
        head = re.split(r"\n---\n", text, maxsplit=1)[0]
        f.write_text(f"{head}\n---\n\n{empty}\n", encoding="utf-8", newline="")


def _set_config(dest: Path, name: str | None, projects_root: str | None) -> None:
    cfg = dest / "lab" / "config.yaml"
    text = cfg.read_text(encoding="utf-8-sig")
    if projects_root:
        text = re.sub(r'^(\s*projects_root:\s*)"[^"]*"', lambda m: f'{m.group(1)}"{projects_root}"', text, count=1, flags=re.M)
    if name:
        safe = name.replace("\\", "").replace('"', "'")[:80]
        if re.search(r"^\s+name:", text.split("\ncompute:", 1)[0], re.M):
            text = re.sub(r'^(\s+name:\s*).*$', lambda m: f'{m.group(1)}"{safe}"', text, count=1, flags=re.M)
        else:
            text = re.sub(r"^(lab:[^\n]*\n)", lambda m: f'{m.group(1)}  name: "{safe}"                # shown in the dashboard\n',
                          text, count=1, flags=re.M)
    cfg.write_text(text, encoding="utf-8", newline="")


def create_lab(dest: str | Path, name: str | None = None, projects_root: str | None = None,
               template: Path = HUB, commit: bool = True) -> dict:
    dest = Path(dest).expanduser().resolve()
    if dest.exists() and any(dest.iterdir()):
        return {"error": f"{dest} already exists and is not empty — pick a new folder"}
    if template.resolve() in (dest, *dest.parents):
        return {"error": "a new lab can't live inside the template itself"}
    dest.mkdir(parents=True, exist_ok=True)
    try:
        n = _export(template, dest)
        _reset_state(dest)
        _set_config(dest, name, projects_root or f"../{dest.name}-projects")
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(dest, ignore_errors=True)
        return {"error": f"could not create the lab: {e}"}
    out = {"ok": True, "path": str(dest), "files": n, "name": name or dest.name, "git": None}
    if shutil.which("git"):
        if _git(["init", "-q"], dest).returncode == 0:
            _git(["add", "-A"], dest)
            out["git"] = "initialized"
            if commit:
                r = _git(["commit", "-q", "-m", "New lab from the Newts' Lab template"], dest)
                out["git"] = "committed" if r.returncode == 0 else \
                    "initialized (files staged — the first commit needs your git name/email)"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dest")
    ap.add_argument("--name")
    ap.add_argument("--projects-root")
    a = ap.parse_args()
    res = create_lab(a.dest, a.name, a.projects_root)
    print(res)
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
