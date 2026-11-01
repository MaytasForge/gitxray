#!/usr/bin/env python3
"""gitxray - рентген для git-репозитория. Ноль зависимостей, только Python 3.8+ и git.

Использование:
    python gitxray.py [путь_к_репозиторию] [--out report.html] [--top 15] [--no-blame]
"""
import argparse
import html
import math
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

__version__ = "0.1.0"

CODE_EXT = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".css", ".scss", ".html", ".go", ".rs",
    ".java", ".kt", ".c", ".h", ".cpp", ".cs", ".rb", ".php", ".vue", ".svelte",
    ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp",
}
ENTRY_STEMS = {
    "main", "index", "app", "__init__", "__main__", "setup", "conftest", "manage",
    "server", "cli", "run", "wsgi", "asgi", "favicon", "readme", "license",
}
TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
WORD_RE = re.compile(r"[\w-]+")
MAX_BYTES = 1_000_000


def git(*args, cwd):
    r = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "git error")
    return r.stdout


def read_text(path):
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:2048]:
        return None
    return data.decode("utf-8", errors="replace")


def load_files(root):
    out = git("ls-files", "-z", cwd=root)
    tracked = [p for p in out.split("\0") if p]
    texts = {}
    for rel in tracked:
        t = read_text(root / rel)
        if t is not None:
            texts[rel] = t
    return tracked, texts


def history(root, tracked):
    """Возвращает (число коммитов на файл, авторы на файл)."""
    alive = set(tracked)
    commits = Counter()
    authors = defaultdict(Counter)
    out = git("log", "--no-merges", "--pretty=format:@@%an", "--name-only", cwd=root)
    author = None
    for line in out.splitlines():
        if line.startswith("@@"):
            author = line[2:]
        elif line and line in alive:
            commits[line] += 1
            authors[line][author] += 1
    return commits, authors


def hotspots(texts, commits, top):
    rows = []
    for f, n in commits.items():
        if f in texts:
            lines = texts[f].count("\n") + 1
            rows.append((f, n, lines, n * math.sqrt(lines)))
    rows.sort(key=lambda r: r[3], reverse=True)
    return rows[:top]


def solo_files(authors, commits, min_commits=3):
    rows = []
    for f, c in authors.items():
        if commits[f] >= min_commits and len(c) == 1:
            rows.append((f, commits[f], next(iter(c))))
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows


def orphans(texts):
    tokens = {f: set(w.lower() for w in WORD_RE.findall(t)) for f, t in texts.items()}
    docfreq = Counter()
    for toks in tokens.values():
        docfreq.update(toks)
    result = []
    for f in texts:
        p = Path(f)
        if p.suffix.lower() not in CODE_EXT:
            continue
        stem = p.name.split(".")[0].lower()
        low = f.lower()
        if stem in ENTRY_STEMS or stem.startswith("test_") or stem.endswith("_test"):
            continue
        if "/test" in "/" + low or "/__tests__/" in low or ".test." in low or ".spec." in low:
            continue
        refs = docfreq[stem] - (1 if stem in tokens[f] else 0)
        if refs <= 0:
            result.append(f)
    return sorted(result)


def old_todos(root, texts, use_blame, limit=80):
    hits = []
    for f, t in texts.items():
        for i, line in enumerate(t.splitlines(), 1):
            if TODO_RE.search(line):
                hits.append((f, i, line.strip()[:110]))
    hits = hits[:limit]
    rows = []
    now = time.time()
    for f, i, text in hits:
        age_days, author = None, "?"
        if use_blame:
            try:
                out = git("blame", "-L", f"{i},{i}", "--porcelain", "--", f, cwd=root)
                m = re.search(r"^author-time (\d+)", out, re.M)
                a = re.search(r"^author (.+)$", out, re.M)
                if m:
                    age_days = int((now - int(m.group(1))) / 86400)
                if a:
                    author = a.group(1)
            except RuntimeError:
                pass
        rows.append((f, i, text, age_days, author))
    rows.sort(key=lambda r: (r[3] is None, -(r[3] or 0)))
    return rows


def health_score(n_files, n_orphans, n_solo, n_touched, todos):
    orphan_ratio = n_orphans / max(n_files, 1)
    solo_ratio = n_solo / max(n_touched, 1)
    stale = sum(1 for t in todos if t[3] is not None and t[3] > 365)
    score = 100 - 40 * orphan_ratio - 40 * solo_ratio - min(20, stale * 2)
    return max(0, min(100, round(score)))


# ---------- вывод ----------

def bar(v, vmax, width=24):
    n = 0 if vmax <= 0 else round(width * v / vmax)
    return "█" * n + "·" * (width - n)


def print_report(d):
    print(f"\n  gitxray {__version__}  ·  {d['name']}")
    print(f"  файлов: {d['n_files']}  ·  коммитов-касаний: {sum(d['commits'].values())}")
    print(f"  ЗДОРОВЬЕ РЕПОЗИТОРИЯ: {d['score']}/100\n")

    print("  🔥 Горячие точки (часто меняются × большие)")
    mx = d["hot"][0][3] if d["hot"] else 1
    for f, n, ln, s in d["hot"][:10]:
        print(f"    {bar(s, mx, 16)} {f}  ({n} изм., {ln} строк)")

    print("\n  🚌 Bus factor = 1 (файлы с одним владельцем)")
    for f, n, a in d["solo"][:10]:
        print(f"    {f}  → {a} ({n} коммитов)")
    if not d["solo"]:
        print("    всё хорошо, у файлов несколько авторов")

    print("\n  👻 Возможные сироты (на файл никто не ссылается)")
    for f in d["orphans"][:10]:
        print(f"    {f}")
    if not d["orphans"]:
        print("    сирот не найдено")

    print("\n  ⏳ Самые старые TODO/FIXME")
    for f, i, text, age, a in d["todos"][:10]:
        age_s = f"{age} дн." if age is not None else "?"
        print(f"    {age_s:>9}  {f}:{i}  [{a}]  {text}")
    print()


def html_report(d):
    esc = html.escape

    def table(head, rows):
        th = "".join(f"<th>{esc(h)}</th>" for h in head)
        trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
        return f"<table><tr>{th}</tr>{trs}</table>" if rows else "<p class=ok>Ничего не найдено 🎉</p>"

    mx = d["hot"][0][3] if d["hot"] else 1
    hot = table(
        ["Файл", "Изменений", "Строк", "Жар"],
        [(f"<code>{esc(f)}</code>", n, ln,
          f"<div class=bar><i style='width:{100 * s / mx:.0f}%'></i></div>")
         for f, n, ln, s in d["hot"]],
    )
    solo = table(["Файл", "Владелец", "Коммитов"],
                 [(f"<code>{esc(f)}</code>", esc(a), n) for f, n, a in d["solo"][:30]])
    orph = table(["Файл"], [(f"<code>{esc(f)}</code>",) for f in d["orphans"][:50]])
    todo = table(["Возраст", "Где", "Автор", "Текст"],
                 [(f"{a} дн." if a is not None else "?", f"<code>{esc(f)}:{i}</code>", esc(au), esc(t))
                  for f, i, t, a, au in d["todos"][:40]])
    color = "#3fb950" if d["score"] >= 70 else "#d29922" if d["score"] >= 40 else "#f85149"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>gitxray · {esc(d['name'])}</title>
<style>
:root{{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--card:#161b22;--line:#30363d;--acc:#58a6ff}}
@media(prefers-color-scheme:light){{:root{{--bg:#fff;--fg:#1f2328;--mut:#656d76;--card:#f6f8fa;--line:#d0d7de;--acc:#0969da}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;padding:24px}}
main{{max-width:960px;margin:auto}}
h1{{margin:0}} .sub{{color:var(--mut)}}
.score{{font-size:64px;font-weight:700;color:{color}}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0;overflow-x:auto}}
table{{border-collapse:collapse;width:100%}} th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}}
th{{color:var(--mut);font-weight:500}} code{{color:var(--acc)}}
.bar{{background:var(--line);border-radius:4px;height:8px;width:140px}} .bar i{{display:block;height:8px;border-radius:4px;background:#f0883e}}
.ok{{color:#3fb950}}
</style></head><body><main>
<h1>🩻 gitxray</h1><div class=sub>{esc(d['name'])} · файлов: {d['n_files']}</div>
<div class=score>{d['score']}<span class=sub style="font-size:24px">/100</span></div>
<section><h2>🔥 Горячие точки</h2>{hot}</section>
<section><h2>🚌 Bus factor = 1</h2>{solo}</section>
<section><h2>👻 Возможные сироты</h2>{orph}</section>
<section><h2>⏳ Старые TODO/FIXME</h2>{todo}</section>
<p class=sub>Эвристики, а не истина: проверяйте перед удалением.</p>
</main></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="gitxray: рентген git-репозитория")
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--out", default="gitxray-report.html", help="куда сохранить HTML-отчёт")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--no-blame", action="store_true", help="быстрее: не считать возраст TODO")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args()

    root = Path(args.path).resolve()
    try:
        git("rev-parse", "--is-inside-work-tree", cwd=root)
    except (RuntimeError, FileNotFoundError):
        sys.exit("Это не git-репозиторий (или git не установлен).")

    tracked, texts = load_files(root)
    commits, authors = history(root, tracked)
    hot = hotspots(texts, commits, args.top)
    solo = solo_files(authors, commits)
    orph = orphans(texts)
    todos = old_todos(root, texts, not args.no_blame)
    score = health_score(len(tracked), len(orph), len(solo), len(commits), todos)

    d = dict(name=root.name, n_files=len(tracked), commits=commits, hot=hot,
             solo=solo, orphans=orph, todos=todos, score=score)
    print_report(d)
    Path(args.out).write_text(html_report(d), encoding="utf-8")
    print(f"  HTML-отчёт: {args.out}\n")


if __name__ == "__main__":
    main()
