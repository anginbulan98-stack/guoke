#!/usr/bin/env python3
"""Sinkronisasi data anime dari SOKUJA (x6.sokuja.uk) ke sokuja-data.js.

Jalankan manual:  python3 tools/sync-sokuja.py
Otomatis:         .github/workflows/sync-sokuja.yml (cron harian).

Output: sokuja-data.js  ->  const SMETA={seriesKey:{t,short,img,score,genre,slug,views,desc}}
                             const SSRC={seriesKey:{ep:{480p:url,720p:url,1080p:url,t:thumb}}}
                             const SEPL={seriesKey:[epN... desc]}

Selain 20 serial langganan, serial BARU yang muncul di "Update Terbaru"
homepage ikut diunduh otomatis (dibatasi) sehingga langsung tampil di aplikasi.
"""
import re
import json
import time
import html as ihtml
import urllib.request
import concurrent.futures
import os

BASE = "https://x6.sokuja.uk"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# serial langganan: key | slug halaman anime
SUBS = """
mushoku|mushoku-tensei-season-3-isekai-ittara-honki-dasu-subtitle-indonesia
onepiece|one-piece-subtitle-indonesia
slime|tensei-shitara-slime-datta-ken-season-4-subtitle-indonesia
psyren|psyren-subtitle-indonesia
goblin|tensei-goblin-dakedo-shitsumon-aru-subtitle-indonesia
overgeared|overgeared-subtitle-indonesia
aoashi|ao-ashi-season-2-subtitle-indonesia
yozakura|yozakura-san-chi-no-daisakusen-season-2-part-2-subtitle-indonesia
aohako|ao-no-hako-season-2-subtitle-indonesia
rezero|rezero-kara-hajimeru-isekai-seikatsu-season-4-subtitle-indonesia
bcs2|black-clover-season-2-subtitle-indonesia
kusuriya|kusuriya-no-hitorigoto-season-3-subtitle-indonesia
chitose|chitose-kun-wa-ramune-bin-no-naka-part-2-subtitle-indonesia
tsucheat|tsuihou-sareta-cheat-fuyo-majutsushi-wa-kimama-na-second-life-wo-ouka-suru-ore-wa-buki-dake-ja-naku-arayuru-mono-ni-kyouka-point-wo-fuyo-dekiru-shi-ore-no-ishi-de-itsudemo-kouka-wo-kaijo-dekiru-kedo-nokotta-hitotachi-daijoubu-subtitle-indonesia
satou|shiotaiou-no-satou-san-ga-ore-ni-dake-amai-subtitle-indonesia
kashita|kashita-maryoku-wa-revo-barai-de-kyousei-choushuu-subtitle-indonesia
kikansha|kikansha-no-mahou-wa-tokubetsu-desu-season-2-subtitle-indonesia
darksummoner|dark-summoner-to-dekiteiru-subtitle-indonesia
kizoku|tensei-kizoku-kantei-skill-de-nariagaru-season-3-subtitle-indonesia
juukishi|tsuihou-sareta-tensei-juukishi-wa-game-chishiki-de-musou-suru-subtitle-indonesia
hikarunatsu|hikaru-ga-shinda-natsu-subtitle-indonesia
maken|nanatsu-no-maken-ga-shihai-suru-subtitle-indonesia
yonkishi|nanatsu-no-taizai-mokushiroku-no-yonkishi-subtitle-indonesia
kyouran|kyouran-reijou-nia-liston-byoujaku-reijou-ni-tensei-shita-kamigoroshi-no-bujin-no-karei-naru-musouroku-subtitle-indonesia
""".strip().splitlines()

# film (tanpa pola episode): key | url halaman tonton | judul tetap
MOVIES = """
edinburgh1|nanatsu-no-taizai-ensa-no-edinburgh-part-1-subtitle-indonesia/|Nanatsu no Taizai: Ensa no Edinburgh Part 1
edinburgh2|nanatsu-no-taizai-ensa-no-edinburgh-part-2-subtitle-indonesia/|Nanatsu no Taizai: Ensa no Edinburgh Part 2
""".strip().splitlines()

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MAX_NEW_SERIES = 25
MAX_EPS = 24


def get(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def short_of(title):
    title = re.sub(r"\s+", " ", title).strip()
    if len(title) <= 26:
        return title
    cut = title[:24].rsplit(" ", 1)[0]
    return (cut or title[:24]) + "..."


def discover():
    """Slug serial dari 'Update Terbaru' homepage (urutan terbaru dulu)."""
    h = get(f"{BASE}/")
    found, seen = [], set()
    for m in re.finditer(r"/([a-z0-9-]+)-episode-\d+-subtitle-indonesia/", h):
        stem = m.group(1)
        if stem not in seen:
            seen.add(stem)
            found.append(stem + "-subtitle-indonesia")
    return found


def series_meta(slug):
    """Ambil meta + daftar episode dari halaman anime. Return (meta, [epN desc])."""
    h = get(f"{BASE}/anime/{slug}/")
    prefix = slug.replace("-subtitle-indonesia", "")
    nums = sorted(
        {int(m) for m in re.findall(re.escape(prefix) + r"-(?:end-)?(?:episode|epsiode)-(\d+)-subtitle-indonesia/", h)},
        reverse=True,
    )[:MAX_EPS]
    t = re.search(r'<meta property="og:title" content="([^"]+)"', h)
    title = ihtml.unescape(t.group(1)).strip() if t else slug.replace("-", " ")
    title = re.sub(r"\s*Subtitle Indonesia\s*$", "", title, flags=re.I).strip() or title
    im = re.search(r'<meta property="og:image" content="([^"]+)"', h)
    img = im.group(1) if im else ""
    if img.startswith("/"):
        img = BASE + img
    d = re.search(r'<meta property="og:description" content="([^"]+)"', h)
    desc = ihtml.unescape(d.group(1)).strip()[:160] if d else ""
    sc = re.search(r'"score":"([\d.]+)"', h)
    score = sc.group(1) if sc else ""
    genres = re.findall(r'/genre/([a-z-]+)/', h)[:2]
    genre = (", ".join(g.capitalize() for g in genres)) if genres else "Anime"
    return {"t": title, "short": short_of(title), "img": img, "score": score,
            "genre": genre, "slug": slug, "views": "-", "desc": desc}, nums


def episode_data_url(full, n):
    for attempt in range(4):
        try:
            h = get(f"{BASE}/{full}")
            m = re.search(r'episodeId\\?":(\d+)', h)
            if not m:
                return n, {"error": "no-eid"}
            t = re.search(r'thumbnailUrl\\?":"([^"\\]+)', h)
            d = json.loads(get(f"{BASE}/api/video-mirrors/?e={m.group(1)}"))
            mp4 = {}
            for mir in d.get("mirrors") or []:
                u = mir.get("embedUrl") or ""
                q = re.search(r"\.(480p|720p|1080p)[-\.]", u)
                if ".mp4" in u:
                    mp4[q.group(1) if q else "default"] = u
            if not mp4:
                return n, {"error": "no-mp4"}
            time.sleep(1.0)
            return n, {"mp4": mp4, "thumb": t.group(1) if t else None}
        except Exception as ex:
            time.sleep(6 + attempt * 4 if "429" in str(ex) else 2)
    return n, {"error": "failed"}


def episode_data(slug, n):
    ep_slug = slug.replace("-subtitle-indonesia", "") + f"-episode-{n}-subtitle-indonesia"
    n2, r = episode_data_url(ep_slug + "/", n)
    r["slug"] = ep_slug
    return n2, r


# sumber cadangan Dailymotion (kurasi manual, id video → series key)
DMFALLBACK = {
 "satou": "xbje77m",
 "doumo-suki-na-hito-ni-horegusuri-wo-irai-sareta-majo-desu": "xbijxcu",
 "sekai-saikyou-no-majo-hajimemashita": "xbkceem",
 "seitokai-ni-mo-ana-wa-aru": "xbl27di",
 "kyouran": "xbje6z6",
}


def main():
    subs = [l.split("|") for l in SUBS]
    sub_slugs = {s for _, s in subs}
    try:
        recent = discover()
        print(f"homepage: {len(recent)} serial terbaru terdeteksi", flush=True)
    except Exception as ex:
        print(f"discover gagal ({str(ex)[:60]}), pakai langganan saja", flush=True)
        recent = []
    series, seen = [], set()
    for key, slug in subs:
        series.append((key, slug))
        seen.add(slug)
    for slug in recent:
        if slug in seen or len(series) >= len(subs) + MAX_NEW_SERIES:
            continue
        key = re.sub(r"-subtitle-indonesia$", "", slug)
        key = re.sub(r"[^a-z0-9]+", "-", key).strip("-")[:60]
        if not key or key in {k for k, _ in series}:
            continue
        series.append((key, slug))
        seen.add(slug)
    print(f"total serial: {len(series)}", flush=True)

    SMETA, SSRC, SEPL = {}, {}, {}
    try:
        raw0 = open(os.path.join(ROOT, "sokuja-data.js")).read()
        def _load(_n):
            _a = raw0.find("const " + _n + "=")
            _b = _a + len("const " + _n + "=")
            _c = [raw0.find("const " + _x + "=", _b) for _x in ("SMETA", "SSRC", "SEPL") if _x != _n]
            _c = [x for x in _c if x >= 0] + [len(raw0)]
            _seg = raw0[_b:min(_c)].rstrip()
            if _seg.endswith(";"):
                _seg = _seg[:-1]
            return json.loads(_seg)
        SMETA, SSRC, SEPL = _load("SMETA"), _load("SSRC"), _load("SEPL")
        print(f"data lama dimuat: {len(SMETA)} serial (digabung, tak ada yang hilang)", flush=True)
    except Exception as ex:
        print(f"mulai fresh ({str(ex)[:50]})", flush=True)
        SMETA, SSRC, SEPL = {}, {}, {}
    total_ok, total_n = 0, 0
    for key, slug in series:
        try:
            meta, nums = series_meta(slug)
        except Exception as ex:
            print(f"{key}: halaman anime gagal ({str(ex)[:60]})", flush=True)
            continue
        if not nums:
            print(f"{key}: tanpa episode, lewati", flush=True)
            continue
        if not meta["img"]:
            print(f"{key}: tanpa poster, lewati", flush=True)
            continue
        SMETA[key] = meta
        print(f"{key}: {meta['t'][:50]} ({len(nums)} ep), resolve video...", flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            futs = {ex.submit(episode_data, slug, n): n for n in nums}
            for fut in concurrent.futures.as_completed(futs):
                n, r = fut.result()
                total_n += 1
                if not r.get("mp4"):
                    continue
                total_ok += 1
                entry = dict(r["mp4"])
                if r.get("thumb"):
                    entry["t"] = r["thumb"]
                SSRC.setdefault(key, {})[str(n)] = entry
        if key in SSRC:
            SEPL[key] = sorted((int(x) for x in SSRC[key]), reverse=True)
        else:
            SMETA.pop(key, None)
            print(f"{key}: tanpa video, lewati", flush=True)
    for line in MOVIES:
        key, full, fixed_title = line.split("|")
        try:
            h = get(f"{BASE}/{full}")
        except Exception as ex:
            print(f"{key}: film gagal ({str(ex)[:60]})", flush=True)
            continue
        t = re.search(r'<meta property="og:title" content="([^"]+)"', h)
        title = ihtml.unescape(t.group(1)).strip() if t else ""
        title = re.sub(r"\s*Subtitle Indonesia\s*$", "", title, flags=re.I).strip()
        if len(title) < 15:
            title = fixed_title
        im = re.search(r'<meta property="og:image" content="([^"]+)"', h)
        img = im.group(1) if im else ""
        if img.startswith("/"):
            img = BASE + img
        if not img:
            print(f"{key}: film tanpa poster, lewati", flush=True)
            continue
        SMETA[key] = {"t": title, "short": title if len(title) <= 26 else title[:24] + "...",
                      "img": img, "score": "", "genre": "Movie",
                      "slug": full.replace("/", ""), "views": "-", "desc": title}
        print(f"{key}: {title[:50]} (film), resolve video...", flush=True)
        n, r = episode_data_url(full, 1)
        total_n += 1
        if r.get("mp4"):
            total_ok += 1
            entry = dict(r["mp4"])
            if r.get("thumb"):
                entry["t"] = r["thumb"]
            SSRC[key] = {"1": entry}
            SEPL[key] = [1]
        else:
            SMETA.pop(key, None)
            print(f"{key}: film tanpa video, lewati", flush=True)
    for _k, _v in DMFALLBACK.items():
        if _k in SMETA:
            SMETA[_k]["alt"] = "dm:" + _v
    out = ("const SMETA=" + json.dumps(SMETA, separators=(",", ":")) + ";\n"
           + "const SSRC=" + json.dumps(SSRC, separators=(",", ":")) + ";\n"
           + "const SEPL=" + json.dumps(SEPL, separators=(",", ":")) + ";")
    with open(os.path.join(ROOT, "sokuja-data.js"), "w") as f:
        f.write(out)
    print(f"SELESAI: {len(SMETA)} serial, {total_ok}/{total_n} episode -> sokuja-data.js ({len(out)} bytes)")


if __name__ == "__main__":
    main()
