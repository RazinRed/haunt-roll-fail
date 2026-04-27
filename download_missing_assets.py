#!/usr/bin/env python3
"""
Download missing HRF assets from https://hrf.im into the local haunt-roll-fail directory.

Reads all asset paths from:
  - hrf.scala  (HRFR.original shared assets)
  - index.html (CSS background images)
  - each game's meta.scala (ConditionalAssetsList / ImageAsset definitions)

Checks which files are absent locally and downloads them from https://hrf.im.

Usage:
    python download_missing_assets.py <path/to/haunt-roll-fail>

Example:
    python download_missing_assets.py D:/Projects/haunt-roll-fail/haunt-roll-fail
"""

import re, sys, urllib.request, urllib.error
from pathlib import Path

REMOTE_BASE = "https://hrf.im/hrf/"

GAMES = ['root','cthw','dwam','vast','arcs','doms','inis','coup','sehi','suok','yarg']


# ---------------------------------------------------------------------------
# Scala source helpers (copied from extract_hrf_assets.py)
# ---------------------------------------------------------------------------

def find_matching_paren(s, start):
    close = {'(': ')', '[': ']', '{': '}'}[s[start]]
    depth, in_str = 0, False
    for i in range(start, len(s)):
        c = s[i]
        if c == '"' and (i == 0 or s[i-1] != '\\'):
            in_str = not in_str
        elif not in_str:
            if c == s[start]:   depth += 1
            elif c == close:
                depth -= 1
                if depth == 0:  return i
    return -1


def outer_split(s):
    depth, in_str, parts, cur = 0, False, [], []
    for c in s:
        if c == '"' and not in_str:     in_str = True;  cur.append(c)
        elif c == '"' and in_str:       in_str = False; cur.append(c)
        elif not in_str:
            if c in '([{':  depth += 1; cur.append(c)
            elif c in ')]}': depth -= 1; cur.append(c)
            elif c == ',' and depth == 0:
                parts.append(''.join(cur).strip()); cur = []
            else: cur.append(c)
        else: cur.append(c)
    if cur: parts.append(''.join(cur).strip())
    return parts


def get_str(s):
    m = re.match(r'(?:\w+\s*=\s*)?"([^"]*)"', s.strip())
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Build complete path set from Scala source
# ---------------------------------------------------------------------------

def collect_paths(haunt_dir):
    """Return sorted list of relative paths (after /hrf/) that should exist locally."""
    haunt = Path(haunt_dir)
    paths = set()

    # 1. HRFR.original entries: "key" -> "/hrf/some/path"
    hrf_scala = haunt / "hrf.scala"
    if hrf_scala.exists():
        for m in re.finditer(r'"/hrf/([\w/.\-]+)"', hrf_scala.read_text(encoding="utf-8")):
            paths.add(m.group(1))

    # 2. CSS backgrounds in index.html: url("omen.png"), url("background.png")
    index_html = haunt / "index.html"
    if index_html.exists():
        for m in re.finditer(r'url\("([\w.\-]+\.png)"\)', index_html.read_text(encoding="utf-8")):
            paths.add(m.group(1))

    # 3. Per-game assets from each game's meta.scala (ConditionalAssetsList / ImageAsset)
    for game in GAMES:
        meta_path = haunt / game / "meta.scala"
        if not meta_path.exists():
            continue
        src = re.sub(r'//[^\n]*', '', meta_path.read_text(encoding='utf-8'))

        pos = 0
        while True:
            m = re.search(r'ConditionalAssetsList\s*\(', src[pos:])
            if not m: break

            ps = pos + m.end() - 1
            pe = find_matching_paren(src, ps)
            if pe < 0: pos = ps + 1; continue

            args = outer_split(src[ps+1:pe])
            cpath, cpfx = '', ''
            for i, a in enumerate(args[1:], 1):
                v = get_str(a)
                if v is None: continue
                if re.match(r'prefix\s*=', a.strip()):  cpfx = v
                elif re.match(r'path\s*=', a.strip()):  cpath = v
                elif i == 1:    cpath = v
                elif i == 2:    cpfx = v

            tail_start = pe + 1
            lm = re.search(r'\s*\(', src[tail_start:tail_start+10])
            if not lm: pos = pe + 1; continue
            ls = tail_start + lm.start()
            le = find_matching_paren(src, ls)
            if le < 0: pos = pe + 1; continue

            lst, ia_pos = src[ls+1:le], 0
            while True:
                ia = re.search(r'ImageAsset\s*\(', lst[ia_pos:])
                if not ia: break
                iap = ia_pos + ia.end() - 1
                iae = find_matching_paren(lst, iap)
                if iae < 0: ia_pos = iap + 1; continue

                parts = outer_split(lst[iap+1:iae])
                name  = get_str(parts[0]) if parts else None
                fname = get_str(parts[1]) if len(parts) > 1 else None
                if name:
                    if not fname: fname = name
                    sub  = f'{cpath}/{fname}.webp' if cpath else f'{fname}.webp'
                    paths.add(f'webp2/{game}/images/{sub}')
                ia_pos = iae + 1

            pos = le + 1

    return sorted(paths)


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    haunt_dir = sys.argv[1]
    haunt = Path(haunt_dir)

    all_paths = collect_paths(haunt_dir)
    print(f"Found {len(all_paths)} tracked asset paths in hrf.scala / index.html / meta.scala files")

    missing = [p for p in all_paths if not (haunt / p).exists()]
    print(f"  {len(all_paths) - len(missing)} already present locally")
    print(f"  {len(missing)} missing — will download from {REMOTE_BASE}")

    if not missing:
        print("Nothing to download.")
        return

    ok, fail = 0, []
    for rel in missing:
        url = REMOTE_BASE + rel
        dest = haunt / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                dest.write_bytes(resp.read())
            print(f"  OK  {rel}")
            ok += 1
        except urllib.error.HTTPError as e:
            print(f"  ERR {rel}  ({e.code} {e.reason})")
            fail.append((rel, str(e)))
        except Exception as e:
            print(f"  ERR {rel}  ({e})")
            fail.append((rel, str(e)))

    print(f"\nDone. {ok} downloaded, {len(fail)} failed.")
    if fail:
        print("Failed:")
        for rel, err in fail:
            print(f"  {rel}: {err}")

    print("\nNext: refresh http://localhost:7070/play/arcs")


if __name__ == "__main__":
    main()
