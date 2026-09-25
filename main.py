import os
import glob
import time
import socket
import threading
from typing import List, Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import yt_dlp

app = FastAPI(
    title="X Media Downloader Tor-Fast Engine",
    version="7.0.0"
)

# CORS Middleware
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

# Round-Robin Cookie Tracking
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
            print("[Tor] Fast IP Switch Requested")
    except Exception:
        pass

def check_tor_active(host="127.0.0.1", port=9050) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.8)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False

def get_proxy_for_attempt(attempt: int) -> Optional[str]:
    tor_active = check_tor_active()

    # Priority 1: Always use Tor first to protect Render Server IP
    if tor_active:
        if attempt > 0:
            trigger_tor_new_ip()
        return TOR_SOCKS_PROXY

    # Priority 2: Custom Proxies fallback
    if CUSTOM_PROXIES:
        return CUSTOM_PROXIES[attempt % len(CUSTOM_PROXIES)]

    return None

def build_yt_dlp_options(proxy: Optional[str], cookie_file: Optional[str]) -> dict:
    opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'skip_download': True,
        'socket_timeout': 4,  # Super fast fail/pass timeout (No 2-minute freeze)
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    }

    if proxy:
        opts['proxy'] = proxy

    if cookie_file:
        opts['cookiefile'] = cookie_file

    return opts

@app.get("/")
def home():
    return {
        "status": "online",
        "engine": "Tor Fast Secure Engine",
        "tor_proxy_active": check_tor_active()
    }

@app.get("/info")
def get_info(url: str = Query(..., description="YouTube Video or Shorts URL")):
    if not url:
        raise HTTPException(status_code=400, detail="URL parameter is required")

    last_error = ""

    for attempt in range(2):  # Reduced to 2 fast attempts
        cookie_file = get_next_cookie_file()
        proxy = get_proxy_for_attempt(attempt)

        ydl_opts = build_yt_dlp_options(proxy, cookie_file)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise Exception("No data extracted")

                formats = []
                raw_formats = info.get("formats", [])
                
                if not raw_formats and info.get("url"):
                    raw_formats = [info]

                for fmt in raw_formats:
                    if fmt.get("url"):
                        res = fmt.get("resolution") or (f"{fmt.get('height')}p" if fmt.get('height') else None) or fmt.get("format_note") or "video/audio"
                        formats.append({
                            "format_id": fmt.get("format_id", "0"),
                            "ext": fmt.get("ext", "mp4"),
                            "resolution": res,
                            "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
                            "vcodec": fmt.get("vcodec"),
                            "acodec": fmt.get("acodec"),
                            "url": fmt.get("url")
                        })

                if not formats and info.get("url"):
                    formats.append({
                        "format_id": "0",
                        "ext": info.get("ext", "mp4"),
                        "resolution": "Original Stream",
                        "filesize": None,
                        "vcodec": None,
                        "acodec": None,
                        "url": info.get("url")
                    })

                return {
                    "title": info.get("title", "YouTube Media"),
                    "duration": info.get("duration"),
                    "thumbnail": info.get("thumbnail"),
                    "uploader": info.get("uploader"),
                    "formats": formats
                }

        except Exception as e:
            last_error = str(e)
            if "bot" in last_error.lower() or "429" in last_error or "reloaded" in last_error:
                trigger_tor_new_ip()

    return JSONResponse(
        status_code=500,
        content={"detail": f"Error extracting media info: {last_error}"}
    )

@app.get("/download")
def download_stream(url: str = Query(...), format_id: Optional[str] = Query(default=None)):
    last_error = ""

    for attempt in range(2):
        cookie_file = get_next_cookie_file()
        proxy = get_proxy_for_attempt(attempt)

        ydl_opts = build_yt_dlp_options(proxy, cookie_file)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise Exception("No stream info received")

                download_url = None

                if format_id and info.get("formats"):
                    for fmt in info["formats"]:
                        if str(fmt.get("format_id")) == str(format_id) and fmt.get("url"):
                            download_url = fmt.get("url")
                            break

                if not download_url:
                    download_url = info.get("url")

                if not download_url and "requested_formats" in info and len(info["requested_formats"]) > 0:
                    download_url = info["requested_formats"][0].get("url")

                if download_url:
                    return {
                        "download_url": download_url,
                        "title": info.get("title"),
                        "ext": info.get("ext", "mp4")
                    }

        except Exception as e:
            last_error = str(e)
            if "bot" in last_error.lower() or "429" in last_error:
                trigger_tor_new_ip()

    return JSONResponse(
        status_code=500,
        content={"detail": f"Error generating download link: {last_error}"}
    )
