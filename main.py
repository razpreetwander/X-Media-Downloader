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
    version="4.0.0"
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
        return False

def get_proxy_for_attempt(attempt: int) -> Optional[str]:
    if attempt == 0:
        return None  # Direct request for maximum speed
    elif attempt == 1 and check_tor_active():
        return TOR_SOCKS_PROXY
    elif CUSTOM_PROXIES:
        return CUSTOM_PROXIES[attempt % len(CUSTOM_PROXIES)]
    return None

def build_yt_dlp_options(proxy: Optional[str], cookie_file: Optional[str]) -> dict:
    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'socket_timeout': 5,  # fast response, no 1 min loading!
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    }

    if proxy:
        opts['proxy'] = proxy

    if cookie_file:
        opts['cookiefile'] = cookie_file

    return opts

@app.get("/")
def home():
    return {"status": "online", "engine": "Fast Pure Audio/Video Engine"}

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
                    filesize = fmt.get("filesize") or fmt.get("filesize_approx")
                    fmt_id = str(fmt.get("format_id", "best"))

                    # MUSIC TAB FILTERING: Only Audios Output
                    if type == "music" or type == "audio":
                        if vcodec == "none" or "audio" in fmt.get("format_note", "").lower():
                            formatted_list.append({
                                "format_id": fmt_id,
                                "ext": fmt.get("ext", "m4a"),
                                "resolution": "Audio Only",
                                "filesize": filesize,
                                "vcodec": "none",
                                "acodec": acodec,
                                "url": fmt_url
                            })
                    # YOUTUBE TAB FILTERING: All Formats
                    else:
                        res = fmt.get("resolution") or (f"{fmt.get('height')}p" if fmt.get('height') else None) or fmt.get("format_note") or "Video"
                        formatted_list.append({
                            "format_id": fmt_id,
                            "ext": fmt.get("ext", "mp4"),
                            "resolution": res,
                            "filesize": filesize,
                            "vcodec": vcodec,
                            "acodec": acodec,
                            "url": fmt_url
                        })

                # Fallback if no specific format extracted
                if not formatted_list and info.get("url"):
                    formatted_list.append({
                        "format_id": "best",
                        "ext": "m4a" if type == "music" else "mp4",
                        "resolution": "Audio Stream" if type == "music" else "Original Stream",
                        "filesize": None,
                        "vcodec": "none" if type == "music" else None,
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
            if "bot" in last_error.lower() or "429" in last_error:
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
                    raise Exception("Failed to load video stream")

                target_url = None

                # Find requested format URL safely
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
            if "bot" in last_error.lower() or "429" in last_error:
                trigger_tor_new_ip()

    return JSONResponse(
        status_code=500,
        content={"detail": f"Error: {last_error}"}
    )
