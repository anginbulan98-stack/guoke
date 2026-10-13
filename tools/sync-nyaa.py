#!/usr/bin/env python3
"""Sinkronisasi tautan torrent Nyaa.si ke nyaa-data.js (sumber unduh cadangan).

Jalankan manual:  python3 tools/sync-nyaa.py
Otomatis:         .github/workflows/sync-sokuja.yml (langkah sesudah Sokuja).

Output: nyaa-data.js -> const TOR={seriesKey:{ep:{magnet,size,seed,tl}}}
Dipakai aplikasi: tab INFO halaman video ("Unduh Torrent").
Magnet dibuka di aplikasi torrent HP (Flud/uTorrent/dll).
"""
import re
import json
import time
import html as ihtml
import urllib.request
import urllib.parse
import os

BASE = "https://nyaa.si"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TRACKERS = [
    "udp://tracker.openbittorrent.com:80/announce",
    "udp://opentracker.i2p.rocks:6969/announce",
    "udp://tracker.opentrackr.org:1337/announce",
]
STOP = {"season", "part", "movie", "the", "no", "wa", "ga", "ni", "de", "wo", "to",
        "s2", "s3", "s4", "ii", "iii", "tv", "ova", "ona", "2nd", "3rd", "sub",
        "indo", "subtitle", "indonesia", "cour", "part"}
BATCH_RX = re.compile(r"E\d+\s*-\s*E?\d+|\bbatch\b|complete", re.I)
BAD_RX = re.compile(r"amv|meme|shorts|tiktok|reaction|lofi|ost |opening|ending", re.I)


def get(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def toks(s):
    return [t for t in re.findall(r"[a-z0-9]+", s.lower())
            if t not in STOP and (len(t) > 2 or t == "ao")]


def rss(q):
    u = BASE + "/?page=rss&q=" + urllib.parse.quote(q) + "&c=1_2&f=0"
    return get(u)


def items_of(xml):
    out = []
    for m in re.finditer(r"<item>([\s\S]*?)</item>", xml):
        it = m.group(1)
        g = lambda p: (re.search(p, it).group(1) if re.search(p, it) else "")
        out.append({"title": ihtml.unescape(g(r"<title>([\s\S]*?)</title>").strip()),
                    "hash": g(r"<nyaa:infoHash>([\s\S]*?)</nyaa:infoHash>").strip(),
                    "seed": g(r"<nyaa:seeders>([\s\S]*?)</nyaa:seeders>").strip(),
                    "size": g(r"<nyaa:size>([\s\S]*?)</nyaa:size>").strip()})
    return out


def epnum(t):
    for p in [r"S\d+E(\d+)", r"\bE(\d+)\b", r"Ep\s*(\d+)", r"Episode\s*(\d+)",
              r"-\s*(\d+)\s*\[", r"\s(\d+)\s*Ticks", r"\s(\d+)\s*\["]:
        m = re.search(p, t, re.I)
        if m:
            return m.group(1)
    return None


def magnet(title, ih):
    dn = urllib.parse.quote(title[:120])
    tr = "&".join("tr=" + urllib.parse.quote(t) for t in TRACKERS)
    return f"magnet:?xt=urn:btih:{ih}&dn={dn}&{tr}"


def series_keys():
    raw = open(os.path.join(ROOT, "sokuja-data.js")).read()
    a = raw.find("const SMETA=")
    b = a + len("const SMETA=")
    cands = [p for p in [raw.find("const " + x + "=", b) for x in ("SMETA", "SSRC", "SEPL")] if p >= 0]
    seg = raw[b:min(cands + [len(raw)])].rstrip()
    SMETA = json.loads(seg[:-1] if seg.endswith(";") else seg)
    return SMETA


def main():
    SMETA = series_keys()
    TOR = {}
    for key, m in SMETA.items():
        st = toks(m.get("t") or "")
        if not st:
            continue
        q = " ".join(st[:4])
        try:
            its = items_of(rss(q))
        except Exception as ex:
            print(f"{key}: RSS gagal ({str(ex)[:50]})", flush=True)
            time.sleep(2)
            continue
        by_ep, batch = {}, None
        for it in its:
            if not it["hash"]:
                continue
            vt = toks(it["title"])
            if len(st) > 1 and sum(1 for t in st if t in vt) < len(st):
                continue
            if len(st) == 1 and st[0] not in vt:
                continue
            try:
                sd = int(it["seed"] or 0)
            except Exception:
                sd = 0
            x264 = 1 if (re.search(r"x264|264|avc|h\.264", it["title"], re.I)
                         and "265" not in it["title"]) else 0
            if BATCH_RX.search(it["title"]):
                if not batch or (x264, sd) > batch[0]:
                    batch = ((x264, sd), it)
                continue
            n = epnum(it["title"])
            if not n:
                continue
            cur = by_ep.get(n)
            if not cur or (x264, sd) > cur[0]:
                by_ep[n] = ((x264, sd), it)
        for n, (sc, it) in by_ep.items():
            TOR.setdefault(key, {})[n] = {
                "magnet": magnet(it["title"], it["hash"]),
                "size": it["size"], "seed": it["seed"],
                "tl": it["title"][:90]}
        if batch:
            sc, it = batch
            TOR.setdefault(key, {})["batch"] = {
                "magnet": magnet(it["title"], it["hash"]),
                "size": it["size"], "seed": it["seed"],
                "tl": it["title"][:90]}
        print(f"{key}: {len(by_ep)} ep" + (" +batch" if batch else ""), flush=True)
        time.sleep(1.0)
    out = "const TOR=" + json.dumps(TOR, separators=(",", ":")) + ";"
    with open(os.path.join(ROOT, "nyaa-data.js"), "w") as f:
        f.write(out)
    print(f"SELESAI: {len(TOR)} serial -> nyaa-data.js ({len(out)} bytes)")


if __name__ == "__main__":
    main()
