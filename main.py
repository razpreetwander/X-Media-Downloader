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
    version="3.1.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# TOR / PROXY CONFIG
# ============================================================

TOR_SOCKS_PROXY = "socks5://127.0.0.1:9050"
TOR_CONTROL_PORT = 9051

RAW_PROXIES = os.getenv("PROXY_URL", "").strip()

CUSTOM_PROXIES: List[str] = [
    p.strip()
    for p in RAW_PROXIES.split(",")
    if p.strip()
]


# ============================================================
# ROUND-ROBIN COOKIE SYSTEM
# ============================================================

cookie_lock = threading.Lock()
cookie_index = 0


def get_next_cookie_file() -> Optional[str]:
    global cookie_index

    cookie_files = sorted(glob.glob("cookies*.txt"))

    if not cookie_files:
        return None

    with cookie_lock:
        selected_cookie = cookie_files[
            cookie_index % len(cookie_files)
        ]

        cookie_index += 1

        print(
            f"[Cookie System] Round-Robin Selected: "
            f"{selected_cookie}"
        )

        return selected_cookie


# ============================================================
# TOR IP RENEWAL
# ============================================================

def trigger_tor_new_ip():
    try:
        with socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        ) as s:

            s.settimeout(2)

            s.connect(
                ("127.0.0.1", TOR_CONTROL_PORT)
            )

            s.sendall(
                b'AUTHENTICATE ""\r\n'
                b'SIGNAL NEWNYM\r\n'
                b'QUIT\r\n'
            )

            print(
                "[Tor System] Successfully requested "
                "NEWNYM."
            )

    except Exception as e:
        print(
            f"[Tor Control Error]: "
            f"Could not renew IP - {e}"
        )


def check_tor_active(
    host="127.0.0.1",
    port=9050
) -> bool:

    try:
        with socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        ) as s:

            s.settimeout(1)

            return (
                s.connect_ex((host, port)) == 0
            )

    except Exception:
        return False


# ============================================================
# PROXY ROTATION
# ============================================================

def get_proxy_for_attempt(
    attempt: int
) -> Optional[str]:

    tor_available = check_tor_active()

    if attempt == 0:

        if tor_available:
            return TOR_SOCKS_PROXY

        elif CUSTOM_PROXIES:
            return CUSTOM_PROXIES[0]


    elif attempt == 1:

        if CUSTOM_PROXIES:

            return CUSTOM_PROXIES[
                attempt % len(CUSTOM_PROXIES)
            ]

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


# ============================================================
# COMMON YT-DLP OPTIONS
# ============================================================

def build_yt_dlp_options(
    proxy: Optional[str],
    cookie_file: Optional[str],
    extra_opts: dict = None
) -> dict:

    opts = {

        "quiet": True,

        "no_warnings": True,

        "extract_flat": False,

        "skip_download": True,

        "format": "*",

        "check_formats": False,

        "user_agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36",

        "extractor_args": {

            "youtube": {

                "player_client": [
                    "android",
                    "ios",
                    "mweb"
                ],

                "skip": [
                    "configs"
                ]
            }
        }
    }


    if proxy:
        opts["proxy"] = proxy


    if cookie_file:
        opts["cookiefile"] = cookie_file


    if extra_opts:
        opts.update(extra_opts)


    return opts


# ============================================================
# COMMON ERROR DETECTION
# ============================================================

def should_rotate_ip(error_text: str) -> bool:

    error_text = error_text.lower()

    error_keywords = [

        "sign in to confirm",

        "bot",

        "429",

        "reloaded",

        "player response",

        "captcha",

        "temporarily unavailable",

        "too many requests"

    ]

    return any(
        keyword in error_text
        for keyword in error_keywords
    )


# ============================================================
# HOME / STATUS
# ============================================================

@app.get("/")
def home():

    tor_status = check_tor_active()

    cookie_count = len(
        glob.glob("cookies*.txt")
    )

    return {

        "status": "online",

        "service":
            "X Media Downloader Ultra Engine",

        "tor_proxy_active":
            tor_status,

        "custom_proxies_loaded":
            len(CUSTOM_PROXIES),

        "total_cookie_files":
            cookie_count,

        "features": [

            "YouTube Video",

            "YouTube Audio/Music",

            "Round-Robin Cookies",

            "Tor Auto-IP Renewal",

            "Proxy Rotation"

        ]
    }


# ============================================================
# YOUTUBE INFO
# ============================================================

@app.get("/info")
def get_info(
    url: str = Query(
        ...,
        description="YouTube Video or Shorts URL"
    )
):

    if not url:
        raise HTTPException(
            status_code=400,
            detail="URL parameter is required"
        )


    last_error = ""


    for attempt in range(3):

        cookie_file = get_next_cookie_file()

        proxy = get_proxy_for_attempt(
            attempt
        )


        print(
            f"[YouTube Info Attempt "
            f"{attempt + 1}/3] "
            f"Proxy: {proxy or 'Direct'} | "
            f"Cookie: {cookie_file or 'None'}"
        )


        ydl_opts = build_yt_dlp_options(
            proxy,
            cookie_file
        )


        try:

            with yt_dlp.YoutubeDL(
                ydl_opts
            ) as ydl:

                info = ydl.extract_info(
                    url,
                    download=False
                )


                if not info:
                    raise Exception(
                        "No data extracted"
                    )


                formats = []

                raw_formats = info.get(
                    "formats",
                    []
                )


                if (
                    not raw_formats
                    and info.get("url")
                ):

                    raw_formats = [info]


                for fmt in raw_formats:

                    if fmt.get("url"):

                        res = (
                            fmt.get("resolution")
                            or (
                                f"{fmt.get('height')}p"
                                if fmt.get("height")
                                else None
                            )
                            or fmt.get("format_note")
                            or "video/audio"
                        )


                        formats.append({

                            "format_id":
                                fmt.get(
                                    "format_id",
                                    "0"
                                ),

                            "ext":
                                fmt.get(
                                    "ext",
                                    "mp4"
                                ),

                            "resolution":
                                res,

                            "filesize":
                                fmt.get(
                                    "filesize"
                                )
                                or fmt.get(
                                    "filesize_approx"
                                ),

                            "vcodec":
                                fmt.get(
                                    "vcodec"
                                ),

                            "acodec":
                                fmt.get(
                                    "acodec"
                                ),

                            "url":
                                fmt.get("url")
                        })


                if (
                    not formats
                    and info.get("url")
                ):

                    formats.append({

                        "format_id":
                            "0",

                        "ext":
                            info.get(
                                "ext",
                                "mp4"
                            ),

                        "resolution":
                            "Original Format",

                        "filesize":
                            None,

                        "vcodec":
                            None,

                        "acodec":
                            None,

                        "url":
                            info.get("url")
                    })


                return {

                    "title":
                        info.get(
                            "title",
                            "YouTube Video"
                        ),

                    "duration":
                        info.get("duration"),

                    "thumbnail":
                        info.get("thumbnail"),

                    "uploader":
                        info.get("uploader"),

                    "formats":
                        formats
                }


        except Exception as e:

            last_error = str(e)

            print(
                f"[YouTube Info Error "
                f"Attempt {attempt + 1}]: "
                f"{last_error}"
            )


            if should_rotate_ip(
                last_error
            ):

                trigger_tor_new_ip()


    return JSONResponse(

        status_code=500,

        content={

            "detail":
                "Failed after 3 automatic retries: "
                + last_error
        }
    )


# ============================================================
# YOUTUBE VIDEO DOWNLOAD / STREAM
# ============================================================

@app.get("/download")
def download_stream(
    url: str = Query(...),
    format_id: str = Query(default=None)
):

    last_error = ""


    for attempt in range(3):

        cookie_file = get_next_cookie_file()

        proxy = get_proxy_for_attempt(
            attempt
        )


        target_fmt = (
            format_id
            if (
                format_id
                and format_id != "best"
            )
            else "*"
        )


        extra_opts = {
            "format": target_fmt
        }


        ydl_opts = build_yt_dlp_options(
            proxy,
            cookie_file,
            extra_opts
        )


        print(
            f"[YouTube Download Attempt "
            f"{attempt + 1}/3] "
            f"Proxy: {proxy or 'Direct'} | "
            f"Cookie: {cookie_file or 'None'} | "
            f"Format: {target_fmt}"
        )


        try:

            with yt_dlp.YoutubeDL(
                ydl_opts
            ) as ydl:

                info = ydl.extract_info(
                    url,
                    download=False
                )


                if not info:
                    raise Exception(
                        "No info received"
                    )


                download_url = info.get(
                    "url"
                )


                if (
                    not download_url
                    and info.get(
                        "requested_formats"
                    )
                ):

                    requested_formats = info.get(
                        "requested_formats"
                    )


                    if requested_formats:

                        download_url = (
                            requested_formats[0]
                            .get("url")
                        )


                if download_url:

                    return {

                        "download_url":
                            download_url,

                        "title":
                            info.get("title"),

                        "ext":
                            info.get("ext")
                    }


                raise Exception(
                    "No direct download URL generated"
                )


        except Exception as e:

            last_error = str(e)

            print(
                f"[YouTube Download Error "
                f"Attempt {attempt + 1}]: "
                f"{last_error}"
            )


            if should_rotate_ip(
                last_error
            ):

                trigger_tor_new_ip()


    return JSONResponse(

        status_code=500,

        content={

            "detail":
                "Failed to generate stream link: "
                + last_error
        }
    )


# ============================================================
# MUSIC / AUDIO
# SAME RETRY + COOKIE + TOR SYSTEM AS YOUTUBE VIDEO
# ============================================================

@app.get("/music")
def music_stream(
    url: str = Query(...),
    format_id: str = Query(default=None)
):

    if not url:

        raise HTTPException(
            status_code=400,
            detail="URL parameter is required"
        )


    last_error = ""


    for attempt in range(3):

        # SAME COOKIE SYSTEM
        cookie_file = get_next_cookie_file()

        # SAME PROXY / TOR SYSTEM
        proxy = get_proxy_for_attempt(
            attempt
        )


        # ----------------------------------------------------
        # MUSIC FORMAT
        # Prefer audio-only formats.
        # If a specific format_id is supplied, use it.
        # ----------------------------------------------------

        if format_id and format_id != "best":

            target_fmt = format_id

        else:

            target_fmt = (
                "bestaudio/"
                "bestaudio[ext=m4a]/"
                "bestaudio[ext=webm]/"
                "best"
            )


        extra_opts = {

            "format":
                target_fmt,

            "noplaylist":
                True
        }


        ydl_opts = build_yt_dlp_options(

            proxy,

            cookie_file,

            extra_opts
        )


        print(

            f"[Music Attempt "
            f"{attempt + 1}/3] "

            f"Proxy: {proxy or 'Direct'} | "

            f"Cookie: {cookie_file or 'None'} | "

            f"Format: {target_fmt}"
        )


        try:

            with yt_dlp.YoutubeDL(
                ydl_opts
            ) as ydl:

                info = ydl.extract_info(
                    url,
                    download=False
                )


                if not info:

                    raise Exception(
                        "No music data extracted"
                    )


                # ------------------------------------------------
                # Direct URL
                # ------------------------------------------------

                download_url = info.get(
                    "url"
                )


                # ------------------------------------------------
                # requested_formats fallback
                # ------------------------------------------------

                if (
                    not download_url
                    and info.get(
                        "requested_formats"
                    )
                ):

                    requested_formats = info.get(
                        "requested_formats"
                    )


                    if requested_formats:

                        # Find an audio stream first
                        audio_format = next(

                            (
                                fmt
                                for fmt
                                in requested_formats

                                if fmt.get(
                                    "acodec"
                                )
                                and fmt.get(
                                    "acodec"
                                ) != "none"
                            ),

                            requested_formats[0]
                        )


                        download_url = (
                            audio_format.get(
                                "url"
                            )
                        )


                # ------------------------------------------------
                # Final URL fallback
                # ------------------------------------------------

if not download_url:

                    for fmt in info.get(
                        "formats",
                        []
                    ):

                        if (
                            fmt.get("url")
                            and fmt.get("acodec")
                            and fmt.get("acodec")
                            != "none"
                        ):

                            download_url = (
                                fmt.get("url")
                            )

                            break


                if download_url:

                    return {

                        "download_url":
                            download_url,

                        "title":
                            info.get(
                                "title"
                            ),

                        "ext":
                            info.get(
                                "ext",
                                "m4a"
                            ),

                        "duration":
                            info.get(
                                "duration"
                            ),

                        "thumbnail":
                            info.get(
                                "thumbnail"
                            ),

                        "uploader":
                            info.get(
                                "uploader"
                            ),

                        "type":
                            "audio"
                    }


                raise Exception(
                    "No direct audio URL generated"
                )


        except Exception as e:

            last_error = str(e)


            print(

                f"[Music Error Attempt "
                f"{attempt + 1}]: "
                f"{last_error}"
            )


            # SAME ERROR HANDLING AS YOUTUBE
            if should_rotate_ip(
                last_error
            ):

                trigger_tor_new_ip()


    return JSONResponse(

        status_code=500,

        content={

            "detail":
                "Failed to generate music stream "
                "after 3 automatic retries: "
                + last_error
        }
    )


# ============================================================
# AUDIO ALIAS
# If frontend calls /audio instead of /music
# ============================================================

@app.get("/audio")
def audio_stream(
    url: str = Query(...),
    format_id: str = Query(default=None)
):

    return music_stream(
        url=url,
        format_id=format_id
    )



# ============================================================
# INSTAGRAM SUPPORT
# Uses the SAME Cookie + Proxy + Tor + Retry System
# ============================================================


def build_instagram_options(
    proxy: Optional[str],
    cookie_file: Optional[str],
    extra_opts: dict = None
) -> dict:

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "skip_download": True,
        "format": "best",
        "check_formats": False,

        "user_agent":
            "Mozilla/5.0 (Linux; Android 13) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/128.0.0.0 Mobile Safari/537.36"
    }

    if proxy:
        opts["proxy"] = proxy

    if cookie_file:
        opts["cookiefile"] = cookie_file

    if extra_opts:
        opts.update(extra_opts)

    return opts


# ============================================================
# INSTAGRAM INFO
# ============================================================

@app.get("/instagram/info")
def instagram_info(
    url: str = Query(...)
):

    if not url:
        raise HTTPException(
            status_code=400,
            detail="Instagram URL is required"
        )

    last_error = ""

    for attempt in range(3):

        cookie_file = get_next_cookie_file()
        proxy = get_proxy_for_attempt(attempt)

        print(
            f"[Instagram Info Attempt "
            f"{attempt + 1}/3] "
            f"Proxy: {proxy or 'Direct'} | "
            f"Cookie: {cookie_file or 'None'}"
        )

        ydl_opts = build_instagram_options(
            proxy,
            cookie_file
        )

        try:

            with yt_dlp.YoutubeDL(
                ydl_opts
            ) as ydl:

                info = ydl.extract_info(
                    url,
                    download=False
                )

                if not info:
                    raise Exception(
                        "No Instagram data extracted"
                    )

                formats = []

                raw_formats = info.get(
                    "formats",
                    []
                )

                if (
                    not raw_formats
                    and info.get("url")
                ):
                    raw_formats = [info]

                for fmt in raw_formats:

                    if not fmt.get("url"):
                        continue

                    formats.append({
                        "format_id":
                            fmt.get(
                                "format_id",
                                "0"
                            ),

                        "ext":
                            fmt.get(
                                "ext",
                                "mp4"
                            ),

                        "resolution":
                            fmt.get(
                                "resolution"
                            )
                            or (
                                f"{fmt.get('height')}p"
                                if fmt.get("height")
                                else "Original"
                            ),

                        "filesize":
                            fmt.get("filesize")
                            or fmt.get(
                                "filesize_approx"
                            ),

                        "vcodec":
                            fmt.get("vcodec"),

                        "acodec":
                            fmt.get("acodec"),

                        "url":
                            fmt.get("url")
                    })

                if (
                    not formats
                    and info.get("url")
                ):

                    formats.append({
                        "format_id": "0",
                        "ext": info.get(
                            "ext",
                            "mp4"
                        ),
                        "resolution": "Original",
                        "filesize": None,
                        "vcodec": info.get(
                            "vcodec"
                        ),
                        "acodec": info.get(
                            "acodec"
                        ),
                        "url": info.get("url")
                    })

                return {
                    "title":
                        info.get(
                            "title",
                            "Instagram Media"
                        ),

                    "duration":
                        info.get("duration"),

                    "thumbnail":
                        info.get("thumbnail"),

                    "uploader":
                        info.get("uploader")
                        or info.get("channel"),

                    "webpage_url":
                        info.get(
                            "webpage_url",
                            url
                        ),

                    "formats":
                        formats
                }

        except Exception as e:

            last_error = str(e)

            print(
                f"[Instagram Info Error "
                f"Attempt {attempt + 1}]: "
                f"{last_error}"
            )

            if should_rotate_ip(
                last_error
            ):
                trigger_tor_new_ip()

    return JSONResponse(
        status_code=500,
        content={
            "detail":
                "Failed after 3 automatic retries: "
                + last_error
        }
    )


# ============================================================
# INSTAGRAM DOWNLOAD
# ============================================================

@app.get("/instagram/download")
def instagram_download(
    url: str = Query(...),
    format_id: str = Query(default=None)
):

    if not url:
        raise HTTPException(
            status_code=400,
            detail="Instagram URL is required"
        )

    last_error = ""

    for attempt in range(3):

        cookie_file = get_next_cookie_file()
        proxy = get_proxy_for_attempt(attempt)

        target_fmt = (
            format_id
            if (
                format_id
                and format_id != "best"
            )
            else "best"
        )

        extra_opts = {
            "format": target_fmt,
            "noplaylist": True
        }

        ydl_opts = build_instagram_options(
            proxy,
            cookie_file,
            extra_opts
        )

        print(
            f"[Instagram Download Attempt "
            f"{attempt + 1}/3] "
            f"Proxy: {proxy or 'Direct'} | "
            f"Cookie: {cookie_file or 'None'} | "
            f"Format: {target_fmt}"
        )

        try:

            with yt_dlp.YoutubeDL(
                ydl_opts
            ) as ydl:

                info = ydl.extract_info(
                    url,
                    download=False
                )

                if not info:
                    raise Exception(
                        "No Instagram info received"
                    )

                download_url = info.get(
                    "url"
                )

                if (
                    not download_url
                    and info.get(
                        "requested_formats"
                    )
                ):

                    requested_formats = info.get(
                        "requested_formats"
                    )

                    if requested_formats:

                        # Prefer video stream
                        video_format = next(
                            (
                                fmt
                                for fmt
                                in requested_formats
                                if fmt.get("vcodec")
                                and fmt.get("vcodec")
                                != "none"
                                and fmt.get("url")
                            ),
                            None
                        )

                        if video_format:
                            download_url = (
                                video_format.get(
                                    "url"
                                )
                            )
                        else:
                            download_url = (
                                requested_formats[0]
                                .get("url")
                            )

                if not download_url:

                    for fmt in info.get(
                        "formats",
                        []
                    ):

                        if fmt.get("url"):

                            download_url = (
                                fmt.get("url")
                            )

                            break

                if download_url:

                    return {
                        "download_url":
                            download_url,

                        "title":
                            info.get(
                                "title"
                            ),

                        "ext":
                            info.get(
                                "ext",
                                "mp4"
                            ),

                        "duration":
                            info.get(
                                "duration"
                            ),

                        "thumbnail":
                            info.get(
                                "thumbnail"
                            ),

                        "uploader":
                            info.get(
                                "uploader"
                            ),

                        "type":
                            "instagram"
                    }

                raise Exception(
                    "No direct Instagram "
                    "download URL generated"
                )

        except Exception as e:

            last_error = str(e)

            print(
                f"[Instagram Download Error "
                f"Attempt {attempt + 1}]: "
                f"{last_error}"
            )

            if should_rotate_ip(
                last_error
            ):
                trigger_tor_new_ip()

    return JSONResponse(
        status_code=500,
        content={
            "detail":
                "Failed to generate Instagram "
                "stream link after 3 automatic retries: "
                + last_error
        }
    )


# ============================================================
# SHORT ALIASES
# ============================================================

@app.get("/insta/info")
def insta_info(
    url: str = Query(...)
):
    return instagram_info(url=url)


@app.get("/insta/download")
def insta_download(
    url: str = Query(...),
    format_id: str = Query(default=None)
):
    return instagram_download(
        url=url,
        format_id=format_id
    )


# ============================================================
# OPTIONAL GENERIC HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
        "youtube": True,
        "music": True,
        "instagram": True,
        "tor": check_tor_active(),
        "cookies": len(
            glob.glob("cookies*.txt")
        ),
        "proxies": len(
            CUSTOM_PROXIES
        )
    }


# ============================================================
# IMPORTANT
# ============================================================
#
# If you already have an Instagram implementation below
# this point from your OLD backend, DO NOT add duplicate
# /instagram/info or /instagram/download routes.
#
# Keep only one implementation of each route.
#
# ============================================================
                