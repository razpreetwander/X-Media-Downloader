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
        print(f"[Cookie System] Round-Robin Selected: {selected_cookie}")
        return selected_cookie

def trigger_tor_new_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(("127.0.0.1", TOR_CONTROL_PORT))
            s.sendall(b'AUTHENTICATE ""\r\nSIGNAL NEWNYM\r\nQUIT\r\n')
            print("[Tor System] Successfully requested NEWNYM (New Circuit / Fresh IP obtained)")
    except Exception as e:
        print(f"[Tor Control Error]: Could not renew IP - {e}")

def check_tor_active(host="127.0.0.1", port=9050) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False

def get_proxy_for_attempt(attempt: int) -> Optional[str]:
    tor_available = check_tor_active()

    if attempt == 0:
        if tor_available:
            return TOR_SOCKS_PROXY
        elif CUSTOM_PROXIES:
            return CUSTOM_PROXIES[0]

    elif attempt == 1:
        if CUSTOM_PROXIES:
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
        'skip_download': True,
        'format': '*',  # Strict filtering disable kardi gayi hai
        'check_formats': False,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'mweb'],
                'skip': ['configs']
            }
        }
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

    for attempt in range(3):
        cookie_file = get_next_cookie_file()
        proxy = get_proxy_for_attempt(attempt)

        print(f"[Attempt {attempt + 1}/3] Fetching info | Proxy: {proxy or 'Direct'} | Cookie: {cookie_file or 'None'}")

        ydl_opts = build_yt_dlp_options(proxy, cookie_file)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise Exception("No data extracted")

                formats = []
                audio_only_formats = []
                raw_formats = info.get("formats", [])
                
                if not raw_formats and info.get("url"):
                    raw_formats = [info]

                for fmt in raw_formats:
                    if fmt.get("url"):
                        vcodec = fmt.get("vcodec")
                        acodec = fmt.get("acodec")
                        res = fmt.get("resolution") or (f"{fmt.get('height')}p" if fmt.get('height') else None) or fmt.get("format_note") or "media"
                        
                        item = {
                            "format_id": fmt.get("format_id", "0"),
                            "ext": fmt.get("ext", "m4a" if vcodec == "none" else "mp4"),
                            "resolution": "Audio Only" if vcodec == "none" else res,
                            "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
                            "vcodec": vcodec,
                            "acodec": acodec,
                            "url": fmt.get("url")
                        }
                        
                        formats.append(item)
                        # Audio-only streams filter
                        if vcodec == "none" and acodec and acodec != "none":
                            audio_only_formats.append(item)

                # Agar frontend audio mangta hai aur alag se audio format mil gaya toh wo prioritise hoga, nahi toh general list jayegi
                output_formats = audio_only_formats if audio_only_formats else formats

                if not output_formats and info.get("url"):
                    output_formats.append({
                        "format_id": "0",
                        "ext": "m4a",
                        "resolution": "Audio Stream",
                        "filesize": None,
                        "vcodec": "none",
                        "acodec": "default",
                        "url": info.get("url")
                    })

                return {
                    "title": info.get("title", "YouTube Audio"),
                    "duration": info.get("duration"),
                    "thumbnail": info.get("thumbnail"),
                    "uploader": info.get("uploader"),
                    "formats": output_formats
                }

        except Exception as e:
            last_error = str(e)
            print(f"[Error Attempt {attempt + 1}]: {last_error}")

            if any(err in last_error.lower() for err in ["sign in to confirm", "bot", "429", "reloaded", "player response"]):
                trigger_tor_new_ip()

    return JSONResponse(
        status_code=500,
        content={"detail": f"Failed after 3 automatic retries: {last_error}"}
    )

@app.get("/download")
def download_stream(url: str = Query(...), format_id: str = Query(default=None)):
    last_error = ""

    for attempt in range(3):
        cookie_file = get_next_cookie_file()
        proxy = get_proxy_for_attempt(attempt)

        # Target format calculation: error prone rigid strings avoid kiye gaye hain
        if format_id and format_id not in ["best", "bestaudio", "audio"]:
            target_fmt = f"{format_id}/*"
        else:
            target_fmt = "*"

        extra_opts = {'format': target_fmt}
        ydl_opts = build_yt_dlp_options(proxy, cookie_file, extra_opts)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise Exception("No info received")

                download_url = info.get("url")

                if not download_url and "requested_formats" in info and len(info["requested_formats"]) > 0:
                    download_url = info["requested_formats"][0].get("url")

                if download_url:
                    return {
                        "download_url": download_url,
                        "title": info.get("title"),
                        "ext": info.get("ext", "m4a")
                    }

        except Exception as e:
            last_error = str(e)
            print(f"[Error Download Attempt {attempt + 1}]: {last_error}")
            
            # Universal Fallback Strategy
            try:
                fallback_opts = build_yt_dlp_options(proxy, cookie_file, {'format': '*'})
                with yt_dlp.YoutubeDL(fallback_opts) as ydl_fb:
                    fb_info = ydl_fb.extract_info(url, download=False)
                    fb_url = fb_info.get("url")
                    if fb_url:
                        return {
                            "download_url": fb_url,
                            "title": fb_info.get("title"),
                            "ext": "m4a"
                        }
            except Exception:
                pass

            if any(err in last_error.lower() for err in ["sign in to confirm", "bot", "reloaded", "player response"]):
                trigger_tor_new_ip()

    return JSONResponse(
        status_code=500,
        content={"detail": f"Failed to generate stream link: {last_error}"}
    )
