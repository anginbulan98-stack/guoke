#!/usr/bin/env python3
"""Sinkronisasi magnet Torrentio (pool global TPB/1337x/dll) ke tio-data.js.

Jalankan manual:  python3 tools/sync-torrentio.py
Otomatis:         .github/workflows/sync-sokuja.yml (langkah sesudah Nyaa).

Alur per serial katalog: IMDb suggest (tanpa key) -> ttID ->
Torrentio stream/series/{tt}:S:E -> magnet per episode.
Hanya episode yg nomor S/E-nya cocok yg disimpan (jujur, anti-salah judul).

Output: tio-data.js -> const TIO={seriesKey:{ep:[{magnet,size,seed,tl,src}]}}
Dipakai aplikasi: tab INFO halaman video (baris Torrentio di bawah Nyaa).
"""
import re
import json
import time
import urllib.request
import urllib.parse
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TRACKERS = [
    "udp://tracker.openbittorrent.com:80/announce",
    "udp://opentracker.i2p.rocks:6969/announce",
    "udp://tracker.opentrackr.org:1337/announce",
]
STOP = {"season", "part", "movie", "the", "sub", "indo", "subtitle", "indonesia",
        "tv", "ova", "ona", "2nd", "3rd", "s2", "s3", "s4", "cour"}
MAX_EPS_PER_SERIES = 6


def get_json(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def toks(s):
    return [t for t in re.findall(r"[a-z0-9]+", s.lower())
            if t not in STOP and len(t) > 2]


def imdb_id(title):
    q = " ".join(toks(title)[:5])
    if not q:
        return None
    d = get_json("https://v3.sg.media-imdb.com/suggestion/x/"
                 + urllib.parse.quote(q) + ".json")
    st = set(toks(title))
    for x in d.get("d") or []:
        if not (x.get("id") or "").startswith("tt"):
            continue
        if x.get("q") not in ("TV series", "TV mini-series"):
            continue
        lt = toks(x.get("l") or "")
        if len(st) > 1 and sum(1 for t in st if t in lt) < max(2, len(st) - 1):
            continue
        if len(st) == 1 and next(iter(st)) not in lt:
            continue
        return x["id"], x.get("l"), x.get("q")
    return None


def season_of(title):
    t = title.lower()
    m = re.search(r"season\s*(\d+)|s(\d+)\b|(\d+)(?:st|nd|rd|th)\s*season|part\s*(\d+)", t)
    if m:
        for g in m.groups():
            if g:
                return int(g)
    return 1


def magnet(title, ih):
    dn = urllib.parse.quote(title[:120])
    tr = "&".join("tr=" + urllib.parse.quote(x) for x in TRACKERS)
    return f"magnet:?xt=urn:btih:{ih}&dn={dn}&{tr}"


def parse_stream(s, season, ep):
    blob = ((s.get("title") or "") + " " + json.dumps(s.get("behaviorHints") or "")).lower()
    pats = [rf"s0*{season}e0*{ep}\b", rf"s0*{season}\s*e0*{ep}\b",
            rf"\b0*{season}x0*{ep}\b", rf"season 0*{season}.*episode 0*{ep}\b"]
    if not any(re.search(p, blob) for p in pats):
        return None
    title = (s.get("title") or "").strip().split("\n")[0][:100]
    if re.search(r"trailer|\bpv\b|promo|teaser|preview|announc|amv|meme|shorts", title, re.I):
        return None
    sd = re.search(r"👤\s*([\d.,]+[KM]?)", s.get("title") or "")
    sz = re.search(r"💾\s*([\d.]+\s*[MG]B)", s.get("title") or "")
    pv = re.search(r"⚙️\s*([A-Za-z0-9]+)", s.get("title") or "")
    return {"magnet": magnet(title, s.get("infoHash", "")),
            "size": sz.group(1) if sz else "-",
            "seed": sd.group(1) if sd else "0",
            "tl": title, "src": pv.group(1) if pv else "P2P"}


def seed_num(x):
    try:
        v = str(x.get("seed") or "0").upper().replace(",", ".")
        m = re.match(r"([\d.]+)\s*([KM]?)", v)
        n = float(m.group(1))
        if m.group(2) == "M":
            n *= 1000000
        elif m.group(2) == "K":
            n *= 1000
        return n
    except Exception:
        return 0


def series_keys():
    raw = open(os.path.join(ROOT, "sokuja-data.js")).read()
    a = raw.find("const SMETA=")
    b = a + len("const SMETA=")
    cands = [p for p in [raw.find("const SSRC=", b)] if p >= 0] + [len(raw)]
    seg = raw[b:min(cands)].rstrip()
    SMETA = json.loads(seg[:-1] if seg.endswith(";") else seg)
    out = {}
    for k, m in SMETA.items():
        out[k] = m.get("t") or k
    return out


def main():
    titles = series_keys()
    TIO = {}
    for key, title in titles.items():
        try:
            found = imdb_id(title)
        except Exception as ex:
            print(f"{key}: imdb gagal ({str(ex)[:50]})", flush=True)
            time.sleep(1)
            continue
        if not found:
            print(f"{key}: tanpa ttID", flush=True)
            time.sleep(0.5)
            continue
        tt, name, kind = found
        season = 1 if kind != "feature" else 0
        if kind != "feature":
            season = season_of(title)
        try:
            raw0 = open(os.path.join(ROOT, "sokuja-data.js")).read()
            a = raw0.find("const SEPL=")
            b = a + len("const SEPL=")
            cands = [len(raw0)]
            seg = raw0[b:].rstrip()
            SEPL = json.loads(seg[:-1] if seg.endswith(";") else seg)
            eps = (SEPL.get(key) or [])[:MAX_EPS_PER_SERIES]
        except Exception:
            eps = []
        got = 0
        for ep in eps:
            try:
                if kind == "feature":
                    d = get_json(f"https://torrentio.strem.fun/stream/movie/{tt}.json")
                else:
                    d = get_json(f"https://torrentio.strem.fun/stream/series/{tt}:{season}:{ep}.json")
            except Exception:
                time.sleep(1)
                continue
            cand = []
            for s in d.get("streams") or []:
                r = parse_stream(s, season, ep)
                if r and s.get("infoHash"):
                    cand.append(r)
            cand.sort(key=seed_num, reverse=True)
            if cand:
                TIO.setdefault(key, {})[str(ep)] = cand[:3]
                got += len(cand[:3])
            time.sleep(0.8)
        print(f"{key}: {tt} S{season} ({name[:45]}) -> {got} magnet", flush=True)
        time.sleep(1.0)
    out = "const TIO=" + json.dumps(TIO, separators=(",", ":")) + ";"
    with open(os.path.join(ROOT, "tio-data.js"), "w") as f:
        f.write(out)
    print(f"SELESAI: {len(TIO)} serial -> tio-data.js ({len(out)} bytes)")


if __name__ == "__main__":
    main()
