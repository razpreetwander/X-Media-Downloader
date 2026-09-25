import os
import glob
import time
import socket
import threading
from typing import List, Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp

app = FastAPI(
    title="X Media Downloader Ultra Engine",
    version="4.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

TOR_SOCKS_PROXY = "socks5://127.0.0.1:9050"
TOR_CONTROL_PORT = 9051

RAW_PROXIES = os.getenv("PROXY_URL", "").strip()
CUSTOM_PROXIES: List[str] = [p.strip() for p in RAW_PROXIES.split(",") if p.strip()]

cookie_lock = threading.Lock()
cookie_index = 0

def get_next_cookie_file() -> Optional[str]:
    global cookie_index
    cookie_files = sorted(glob.glob("cookies*.txt"))
    if not cookie_files:
        return None

    with cookie_lock:
        selected_cookie = cookie_files[cookie_index % len(cookie_files)]
        cookie_index += 1
        return selected_cookie

def trigger_tor_new_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(("127.0.0.1", TOR_CONTROL_PORT))
            s.sendall(b'AUTHENTICATE ""\r\nSIGNAL NEWNYM\r\nQUIT\r\n')
    except Exception:
        pass

def check_tor_active(host="127.0.0.1", port=9050) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex((host, port)) == 0
    except Exception:
        False

def get_proxy_for_attempt(attempt: int) -> Optional[str]:
    if attempt == 0:
        return None
    elif attempt == 1 and check_tor_active():
        return TOR_SOCKS_PROXY
    elif CUSTOM_PROXIES:
        return CUSTOM_PROXIES[attempt % len(CUSTOM_PROXIES)]
    return None

# Helper function to format bytes into readable MB/GB
def format_bytes(size_in_bytes: Optional[int]) -> str:
    if not size_in_bytes:
        return ""
    mb = size_in_bytes / (1024 * 1024)
    if mb >= 1024:
        return f" ({mb / 1024:.2f} GB)"
    return f" ({mb:.1f} MB)"

# Helper function to clean resolution labels (e.g. 1080p, 4K)
def clean_resolution(fmt: dict) -> str:
    height = fmt.get("height")
    note = str(fmt.get("format_note", "")).upper()
    vcodec = fmt.get("vcodec", "")

    if vcodec == "none":
        return "Audio Only"

    if height:
        if height >= 2160:
            return "4K (2160p)"
        elif height >= 1440:
            return "2K (1440p)"
        elif height >= 1080:
            return "1080p (FHD)"
        elif height >= 720:
            return "720p (HD)"
        elif height >= 480:
            return "480p"
        elif height >= 360:
            return "360p"
        elif height >= 240:
            return "240p"
        elif height >= 144:
            return "144p"
        return f"{height}p"

    if "1080" in note:
        return "1080p (FHD)"
    elif "720" in note:
        return "720p (HD)"
    elif "4K" in note or "2160" in note:
        return "4K (2160p)"

    return "Video"

def build_yt_dlp_options(proxy: Optional[str], cookie_file: Optional[str]) -> dict:
    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'socket_timeout': 6,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'extractor_args': {
            'youtube': {
                'player_client': ['mweb', 'android', 'ios'],
                'skip': ['configs']
            }
        }
    }

    if proxy:
        opts['proxy'] = proxy

    if cookie_file:
        opts['cookiefile'] = cookie_file

    return opts

@app.get("/")
def home():
    return {"status": "online", "engine": "X Media Downloader Hybrid Engine"}

@app.get("/info")
def get_info(url: str = Query(...), type: Optional[str] = Query(default="video")):
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    last_error = ""

    for attempt in range(3):
        cookie_file = get_next_cookie_file()
        proxy = get_proxy_for_attempt(attempt)

        ydl_opts = build_yt_dlp_options(proxy, cookie_file)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise Exception("Unable to extract info")

                all_formats = info.get("formats", [])
                if not all_formats and info.get("url"):
                    all_formats = [info]

                formatted_list = []

                for fmt in all_formats:
                    fmt_url = fmt.get("url")
                    if not fmt_url:
                        continue

                    vcodec = fmt.get("vcodec", "")
                    acodec = fmt.get("acodec", "")
                    raw_size = fmt.get("filesize") or fmt.get("filesize_approx")
                    size_str = format_bytes(raw_size)
                    fmt_id = str(fmt.get("format_id", "best"))

                    # MUSIC TAB FILTERING: Only Audio streams
                    if type in ["music", "audio"]:
                        if vcodec == "none" and acodec and acodec != "none":
                            ext_type = fmt.get("ext", "m4a")
                            formatted_list.append({
                                "format_id": fmt_id,
                                "ext": ext_type,
                                "resolution": f"Audio ({ext_type.upper()}){size_str}",
                                "filesize": raw_size,
                                "vcodec": "none",
                                "acodec": acodec,
                                "url": fmt_url
                            })

                    # VIDEO TAB FILTERING: Clean resolutions + Size
                    else:
                        res_label = clean_resolution(fmt)
                        formatted_list.append({
                            "format_id": fmt_id,
                            "ext": fmt.get("ext", "mp4"),
                            "resolution": f"{res_label}{size_str}",
                            "filesize": raw_size,
                            "vcodec": vcodec,
                            "acodec": acodec,
                            "url": fmt_url
                        })

                # Fallback strategy
                if not formatted_list and info.get("url"):
                    size_str = format_bytes(info.get("filesize") or info.get("filesize_approx"))
                    formatted_list.append({
                        "format_id": "best",
                        "ext": "m4a" if type in ["music", "audio"] else "mp4",
                        "resolution": ("Audio Stream" if type in ["music", "audio"] else "Standard Quality") + size_str,
                        "filesize": None,
                        "vcodec": "none" if type in ["music", "audio"] else None,
                        "acodec": "default",
                        "url": info.get("url")
                    })

                return {
                    "title": info.get("title", "Media"),
                    "duration": info.get("duration"),
                    "thumbnail": info.get("thumbnail"),
                    "uploader": info.get("uploader"),
                    "formats": formatted_list
                }

        except Exception as e:
            last_error = str(e)
            if any(err in last_error.lower() for err in ["reloaded", "bot", "429", "confirm"]):
                trigger_tor_new_ip()

    return JSONResponse(
        status_code=500,
        content={"detail": f"Error: {last_error}"}
    )

@app.get("/download")
def download_stream(url: str = Query(...), format_id: Optional[str] = Query(default=None)):
    last_error = ""

    for attempt in range(3):
        cookie_file = get_next_cookie_file()
        proxy = get_proxy_for_attempt(attempt)

        ydl_opts = build_yt_dlp_options(proxy, cookie_file)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise Exception("Failed to load stream")

                target_url = None

                if format_id and info.get("formats"):
                    for fmt in info["formats"]:
                        if str(fmt.get("format_id")) == str(format_id) and fmt.get("url"):
                            target_url = fmt.get("url")
                            break

                if not target_url:
                    target_url = info.get("url")

                if not target_url and "requested_formats" in info:
                    target_url = info["requested_formats"][0].get("url")

                if target_url:
                    return {
                        "download_url": target_url,
                        "title": info.get("title"),
                        "ext": info.get("ext", "mp4")
                    }

        except Exception as e:
            last_error = str(e)
            if any(err in last_error.lower() for err in ["reloaded", "bot", "429"]):
                trigger_tor_new_ip()

    return JSONResponse(
        status_code=500,
        content={"detail": f"Error: {last_error}"}
    )
