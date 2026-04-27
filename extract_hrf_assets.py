#!/usr/bin/env python3
"""
Extract game assets from an offline HRF HTML file into the correct
haunt-roll-fail directory structure so the sbt server build works.

Usage:
    python extract_hrf_assets.py <offline.html> <path/to/haunt-roll-fail>

Example:
    python extract_hrf_assets.py hrf--arcs--0.8.140--offline.html D:/Projects/haunt-roll-fail/haunt-roll-fail
"""

import re, base64, sys
from pathlib import Path
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

class HRFHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = {}   # key -> data_url  (game images)

    def handle_starttag(self, tag, attrs):
        if tag != 'img':
            return
        d = dict(attrs)
        id_ = d.get('id', '')
        src = d.get('src', '')
        if id_.startswith('asset-') and src.startswith('data:'):
            self.assets[id_[6:]] = src   # strip "asset-" prefix


# ---------------------------------------------------------------------------
# Scala source parsing helpers
# ---------------------------------------------------------------------------

def find_matching_paren(s, start):
    """Return index of the closing paren/brace/bracket matching s[start]."""
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
    """Split s by top-level commas (ignoring those inside parens/braces/strings)."""
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
    """Return string literal value from 'name = "val"' or '"val"', else None."""
    m = re.match(r'(?:\w+\s*=\s*)?"([^"]*)"', s.strip())
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Build key -> relative-path mapping from Scala source
# ---------------------------------------------------------------------------

def build_asset_map(haunt_dir):
    haunt = Path(haunt_dir)
    result = {}

    # 1. Shared assets explicitly listed in hrf.scala (HRFR.original block)
    #    Pattern: "key" -> "/hrf/some/path.ext"
    hrf_scala = haunt / 'hrf.scala'
    if hrf_scala.exists():
        for m in re.finditer(r'"([\w-]+)"\s*->\s*"/hrf/([\w/.-]+)"',
                             hrf_scala.read_text(encoding='utf-8')):
            result[m.group(1)] = m.group(2)   # e.g. "webp2/root/images/icon/battle.webp"

    # 2. Per-game assets from each game's meta.scala
    #    ConditionalAssetsList(condition, path?, prefix?, ...)(ImageAsset(...) :: ...)
    games = ['root','cthw','dwam','vast','arcs','doms','inis','coup','sehi','suok','yarg']
    for game in games:
        meta_path = haunt / game / 'meta.scala'
        if not meta_path.exists():
            continue
        src = re.sub(r'//[^\n]*', '', meta_path.read_text(encoding='utf-8'))

        pos = 0
        while True:
            m = re.search(r'ConditionalAssetsList\s*\(', src[pos:])
            if not m: break

            ps = pos + m.end() - 1          # position of opening '('
            pe = find_matching_paren(src, ps)
            if pe < 0: pos = ps + 1; continue

            # Parse path / prefix from condition args (args[1], args[2])
            args = outer_split(src[ps+1:pe])
            cpath, cpfx = '', ''
            for i, a in enumerate(args[1:], 1):
                v = get_str(a)
                if v is None: continue
                if re.match(r'prefix\s*=', a.strip()):  cpfx = v
                elif re.match(r'path\s*=', a.strip()):  cpath = v
                elif i == 1:    cpath = v   # 2nd positional = subdirectory path
                elif i == 2:    cpfx = v    # 3rd positional = key prefix

            # Find the second () immediately after — the asset list
            tail_start = pe + 1
            lm = re.search(r'\s*\(', src[tail_start:tail_start+10])
            if not lm: pos = pe + 1; continue
            ls = tail_start + lm.start()
            le = find_matching_paren(src, ls)
            if le < 0: pos = pe + 1; continue

            # Find all ImageAsset() calls inside the list
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
                    key  = cpfx + name
                    sub  = f'{cpath}/{fname}.webp' if cpath else f'{fname}.webp'
                    result[key] = f'webp2/{game}/images/{sub}'
                ia_pos = iae + 1

            pos = le + 1

    return result


# ---------------------------------------------------------------------------
# Decode base64 data URL
# ---------------------------------------------------------------------------

def decode(data_url):
    try:
        return base64.b64decode(data_url.split(',', 1)[1])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def extract_fonts(html_text, index_html_path, haunt):
    """Extract embedded fonts from offline HTML and save to fonts/."""
    # Build family -> filename map from the original index.html
    # e.g. @font-face { font-family: "Luminari"; src: url("fonts/luminari.woff2") ... }
    family_to_file = {}
    try:
        index = Path(index_html_path).read_text(encoding='utf-8')
        blocks = re.findall(
            r'@font-face\s*\{([^}]+)\}', index, re.DOTALL)
        for block in blocks:
            fam = re.search(r'font-family:\s*"([^"]+)"', block)
            urls = re.findall(r'url\("([^"]+)"\)', block)
            if fam and urls:
                family_to_file[fam.group(1)] = urls   # list of filenames
    except Exception as e:
        print(f'  Warning: could not read index.html for font map: {e}')
        return 0

    # Parse @font-face blocks in offline HTML
    # Fonts are embedded as: url(data:font/woff2;base64,...) format("woff2")
    saved = 0
    blocks = re.findall(r'@font-face\s*\{([^}]+)\}', html_text, re.DOTALL)
    for block in blocks:
        fam_m = re.search(r'font-family:\s*"([^"]+)"', block)
        if not fam_m:
            continue
        family = fam_m.group(1)
        filenames = family_to_file.get(family, [])

        # Extract data URLs: url(data:font/TYPE;base64,DATA) format("EXT")
        entries = re.findall(
            r'url\(data:font/[^;]+;base64,([^)]+)\)\s*format\("([^"]+)"', block)

        for (b64data, fmt), fname in zip(entries, filenames):
            out = haunt / fname
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                out.write_bytes(base64.b64decode(b64data.strip()))
                saved += 1
            except Exception as e:
                print(f'  Warning: could not save {fname}: {e}')

    return saved


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    html_file  = sys.argv[1]
    haunt_dir  = sys.argv[2]
    haunt      = Path(haunt_dir)

    # --- Parse HTML ---
    print(f'Reading {html_file} ...')
    html_text = Path(html_file).read_text(encoding='utf-8')

    parser = HRFHTMLParser()
    parser.feed(html_text)
    print(f'  {len(parser.assets)} embedded game images found')

    # --- Build asset map ---
    print('Building path map from Scala source ...')
    asset_map = build_asset_map(haunt_dir)
    print(f'  {len(asset_map)} mappings built')

    # --- Save game images ---
    saved, unmapped = 0, []
    for key, data_url in parser.assets.items():
        rel = asset_map.get(key)
        if not rel:
            unmapped.append(key)
            continue
        out = haunt / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        data = decode(data_url)
        if data:
            out.write_bytes(data)
            saved += 1

    # --- Save fonts ---
    index_html = Path(haunt_dir) / 'index.html'
    font_saved = extract_fonts(html_text, index_html, haunt)

    # --- Summary ---
    print(f'\nDone.')
    print(f'  {saved} game images saved to webp2/')
    print(f'  {font_saved} font files saved to fonts/')
    if unmapped:
        print(f'\n  {len(unmapped)} keys had no path mapping (version-newer assets, safe to ignore):')
        for k in unmapped[:15]:
            print(f'    {k}')
        if len(unmapped) > 15:
            print(f'    ... and {len(unmapped)-15} more')

    print('\nNext: refresh http://localhost:7070/play/arcs')


if __name__ == '__main__':
    main()
