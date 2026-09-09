import json
import os
import subprocess
import sys
import datetime
import urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
CFG_PATH = os.path.join(BASE, "channels.json")
CLIENTS = "youtube:player_client=android,android_vr,ios"
ITAGS = (18, 22, 34)
YT_TIMEOUT = 120

CURL = "/usr/bin/curl" if os.path.exists("/usr/bin/curl") else "curl"


def call(cmd, timeout):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired:
        return None, None


def ytdlp(args, timeout=YT_TIMEOUT):
    candidates = [
        ["yt-dlp"] + args,
        [sys.executable, "-m", "yt_dlp"] + args,
    ]
    for c in candidates:
        code, out = call(c, timeout)
        if code == 0 and out:
            return out
    return None


def flat_videos(handle, maxv):
    url = f"https://www.youtube.com/{handle}/videos"
    out = ytdlp(["--flat-playlist", "--playlist-end", str(maxv),
                 "--print", "%(id)s\u0001%(title)s", url])
    if not out:
        return []
    items = []
    for line in out.strip().splitlines():
        if "\u0001" in line:
            vid, title = line.split("\u0001", 1)
            items.append((vid, title))
    return items


def single_url(vid):
    for itag in ITAGS:
        out = ytdlp(["-J", "-f", str(itag), "--skip-download",
                     "--extractor-args", CLIENTS,
                     f"https://www.youtube.com/watch?v={vid}"], timeout=90)
        if not out:
            continue
        try:
            info = json.loads(out)
        except Exception:
            continue
        fmts = info.get("requested_formats") or ([info] if info.get("url") else [])
        sel = next((x for x in fmts if x.get("url")), None)
        if not sel:
            continue
        if sel.get("vcodec") != "none" and sel.get("acodec") != "none":
            return sel["url"], sel.get("format_id"), sel.get("height")
    return None, None, None


def verify(url):
    if os.environ.get("NO_VERIFY") == "1":
        return True
    for _ in range(2):
        try:
            p = subprocess.run([CURL, "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                "--max-time", "40", "-r", "0-1023", url],
                               capture_output=True, text=True)
            code = p.stdout.strip()
            if code.startswith("2") or code.startswith("3"):
                return True
        except Exception:
            pass
    return False


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    config = json.load(open(CFG_PATH, encoding="utf-8"))
    for ch in config:
        handle = ch["handle"]
        maxv = int(ch.get("max_videos", 10))
        fname = os.path.join(DATA_DIR, ch["id"] + ".json")
        existing = []
        if os.path.exists(fname):
            existing = json.load(open(fname, encoding="utf-8")).get("videos", [])
        by_id = {v["id"]: v for v in existing}
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        flat = flat_videos(handle, maxv)
        if not flat:
            print(f"[{ch['name']}] ERROR: could not fetch video list")
            continue

        refreshed = 0
        added = 0
        kept = 0
        ordered = []
        for vid, title in flat:
            if vid in by_id:
                entry = by_id[vid]
                kept += 1
            else:
                entry = {"id": vid, "title": title, "added_at": now}
                added += 1
            entry["title"] = title
            entry["webpage"] = f"https://www.youtube.com/watch?v={vid}"
            ordered.append(entry)
        ordered = ordered[:maxv]

        for entry in ordered:
            url, fmt, height = single_url(entry["id"])
            if url and verify(url):
                entry["url"] = url
                entry["format"] = fmt
                entry["height"] = height
                entry.pop("error", None)
                refreshed += 1
                tb = ch.get("tunnel_base")
                if tb:
                    entry["tunnel_url"] = tb + urllib.parse.quote(url, safe="")
            elif "url" not in entry:
                entry["url"] = None
                entry["format"] = None
                entry["height"] = None
                entry["error"] = "could not generate single-file link"
            entry["refreshed_at"] = now

        doc = {"channel": ch, "updated_at": now, "videos": ordered}
        json.dump(doc, open(fname, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"[{ch['name']}] added={added} refreshed={refreshed} kept={kept} total={len(ordered)}")


if __name__ == "__main__":
    main()