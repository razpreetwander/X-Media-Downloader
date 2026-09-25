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
    title="X Media Downloader Ultra-Reliable API",
    description="Backend with Round-Robin Cookies, Tor Auto-IP Renewal and Webshare Fallback.",
    version="3.0.0"
)

# CORS Middleware (Frontend with zero changes supported)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

TOR_SOCKS_PROXY = "socks5://127.0.0.1:9050"
TOR_CONTROL_PORT = 9051

# Multiple Webshare / Custom proxies support (Comma separated in env variable)
# Example: "http://user:pass@proxy1:8080,http://user:pass@proxy2:8080"
RAW_PROXIES = os.getenv("PROXY_URL", "").strip()
CUSTOM_PROXIES: List[str] = [p.strip() for p in RAW_PROXIES.split(",") if p.strip()]

# Round-Robin Cookie Tracking
cookie_lock = threading.Lock()
cookie_index = 0

def get_next_cookie_file() -> Optional[str]:
    """
    1st Req -> cookie1.txt, 2nd Req -> cookie2.txt, ... 
    Iterates sequentially through all available cookies and loops back to 1.
    """
    global cookie_index
    cookie_files = sorted(glob.glob("cookies*.txt"))
    if not cookie_files:
        return None

    with cookie_lock:
        selected_cookie = cookie_files[cookie_index % len(cookie_files)]
        cookie_index += 1
        print(f"[Cookie System] Round-Robin Selected: {selected_cookie}")
        return selected_cookie

def trigger_tor_new_ip():
    """
    Sends SIGNAL NEWNYM to Tor Control Port to instantly obtain a fresh Exit IP.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(("127.0.0.1", TOR_CONTROL_PORT))
            s.sendall(b'AUTHENTICATE ""\r\nSIGNAL NEWNYM\r\nQUIT\r\n')
            print("[Tor System] Successfully requested NEWNYM (New Circuit / Fresh IP obtained)")
    except Exception as e:
        print(f"[Tor Control Error]: Could not renew IP - {e}")

def check_tor_active(host="127.0.0.1", port=9050) -> bool:
    """Checks if local Tor SOCKS5 daemon is running."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False

def get_proxy_for_attempt(attempt: int) -> Optional[str]:
    """
    Returns proxy based on attempt count:
    Attempt 0: Try Tor SOCKS5
    Attempt 1: Try Custom Webshare Proxy (if provided)
    Attempt 2: Request New Tor IP and try Tor again
    Attempt 3: Direct connection fallback
    """
    tor_available = check_tor_active()

    if attempt == 0:
        if tor_available:
            return TOR_SOCKS_PROXY
        elif CUSTOM_PROXIES:
            return CUSTOM_PROXIES[0]

    elif attempt == 1:
        if CUSTOM_PROXIES:
            # Pick a proxy based on attempt
            return CUSTOM_PROXIES[attempt % len(CUSTOM_PROXIES)]
        elif tor_available:
            trigger_tor_new_ip()
            time.sleep(1)
            return TOR_SOCKS_PROXY

    elif attempt == 2:
        if tor_available:
            trigger_tor_new_ip()
            time.sleep(1.5)
            return TOR_SOCKS_PROXY

    return None

def build_yt_dlp_options(proxy: Optional[str], cookie_file: Optional[str], extra_opts: dict = None) -> dict:
    opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'skip_download': True, # Keep server RAM/disk safe
    }

    if proxy:
        opts['proxy'] = proxy

    if cookie_file:
        opts['cookiefile'] = cookie_file

    if extra_opts:
        opts.update(extra_opts)

    return opts

@app.get("/")
def home():
    tor_status = check_tor_active()
    cookie_count = len(glob.glob("cookies*.txt"))
    return {
        "status": "online",
        "service": "X Media Downloader Ultra Engine",
        "tor_proxy_active": tor_status,
        "custom_proxies_loaded": len(CUSTOM_PROXIES),
        "total_cookie_files": cookie_count
    }

@app.get("/info")
def get_info(url: str = Query(..., description="YouTube Video or Shorts URL")):
    if not url:
        raise HTTPException(status_code=400, detail="URL parameter is required")

    last_error = ""

    # Maximum 3 attempts with automated fallback, new IP & next cookie
    for attempt in range(3):
        cookie_file = get_next_cookie_file()
        proxy = get_proxy_for_attempt(attempt)

        print(f"[Attempt {attempt + 1}/3] Fetching info | Proxy: {proxy or 'Direct'} | Cookie: {cookie_file or 'None'}")

        ydl_opts = build_yt_dlp_options(proxy, cookie_file)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                formats = []
                for fmt in info.get("formats", []):
                    if fmt.get("url"):
                        formats.append({
                            "format_id": fmt.get("format_id"),
                            "ext": fmt.get("ext"),
                            "resolution": fmt.get("resolution") or fmt.get("format_note") or "audio only",
                            "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
                            "vcodec": fmt.get("vcodec"),
                            "acodec": fmt.get("acodec"),
                            "url": fmt.get("url")
                        })

                return {
                    "title": info.get("title"),
                    "duration": info.get("duration"),
                    "thumbnail": info.get("thumbnail"),
                    "uploader": info.get("uploader"),
                    "formats": formats
                }

        except Exception as e:
            last_error = str(e)
            print(f"[Error Attempt {attempt + 1}]: {last_error}")
            
            # If bot detection or sign in error occurred, trigger new Tor IP for next try
            if "Sign in to confirm" in last_error or "bot" in last_error.lower() or "429" in last_error:
                trigger_tor_new_ip()

    # If all 3 attempts fail, return structured error
    return JSONResponse(
        status_code=500,
        content={"detail": f"Failed after 3 automatic retries: {last_error}"}
    )

@app.get("/download")
def download_stream(url: str = Query(...), format_id: str = Query(default="best")):
    last_error = ""

    for attempt in range(3):
        cookie_file = get_next_cookie_file()
        proxy = get_proxy_for_attempt(attempt)

        ydl_opts = build_yt_dlp_options(proxy, cookie_file, {'format': format_id})

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                download_url = info.get("url")

                if not download_url and "requested_formats" in info:
                    download_url = info["requested_formats"][0].get("url")

                if download_url:
                    return {
                        "download_url": download_url,
                        "title": info.get("title"),
                        "ext": info.get("ext")
                    }

        except Exception as e:
            last_error = str(e)
            print(f"[Error Download Attempt {attempt + 1}]: {last_error}")
            if "Sign in to confirm" in last_error or "bot" in last_error.lower():
                trigger_tor_new_ip()

    return JSONResponse(
        status_code=500,
        content={"detail": f"Failed to generate stream link: {last_error}"}
    )