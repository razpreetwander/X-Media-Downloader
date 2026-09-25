import glob
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI(title="X Media Downloader API")

# Allow CORS for Web & Mobile webview apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "status": "Online",
        "service": "X Media Downloader API",
        "endpoints": ["/info?url=...", "/download?url=...&format_id=..."],
    }


@app.get("/health")
def health():
    return {"ok": True}


def validate_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL")
    return url


def get_common_ydl_opts():
    """
    YouTube Bot Detection और 'Sign in to confirm you're not a bot' एरर 
    को बाईपास करने के लिए एडवांस कॉन्फ़िगरेशन।
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        # Browser Headers mimic करना
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
        # Client spoofing - YouTube Bot Detection बाईपास करने की सबसे मुख्य ट्रिक
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "android", "mweb"],
                "skip": ["hls", "dash"],
            }
        },
    }

    # अगर आपने root directory में cookies.txt रखी होगी तो यह अपने आप उसे यूज़ कर लेगा
    if os.path.exists("cookies.txt"):
        opts["cookiefile"] = "cookies.txt"

    return opts


@app.get("/info")
def get_info(url: str):
    url = validate_url(url)

    ydl_opts = get_common_ydl_opts()
    ydl_opts["skip_download"] = True

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        seen = set()

        for f in (info.get("formats") or []):
            format_id = f.get("format_id")
            ext = (f.get("ext") or "").lower()

            if not format_id or ext not in {"mp4", "webm", "m4a", "mp3", "opus"}:
                continue

            key = str(format_id)
            if key in seen:
                continue
            seen.add(key)

            height = f.get("height")
            resolution = f.get("resolution")
            if not resolution and height:
                resolution = f"{height}p"

            formats.append({
                "format_id": str(format_id),
                "resolution": resolution or "Audio",
                "ext": ext,
                "format_note": f.get("format_note") or "",
                "filesize": f.get("filesize") or f.get("filesize_approx"),
                "vcodec": f.get("vcodec"),
                "acodec": f.get("acodec"),
                "fps": f.get("fps"),
            })

        # Sort: Resolution highest first, then formats
        def sort_key(f):
            height = 0
            r = f.get("resolution") or ""
            if r.endswith("p"):
                try:
                    height = int(r[:-1])
                except ValueError:
                    pass
            return (height, 1 if f["ext"] in {"mp4", "webm"} else 0)

        formats.sort(key=sort_key, reverse=True)

        return {
            "title": info.get("title") or "Untitled",
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "uploader": info.get("uploader"),
            "webpage_url": info.get("webpage_url") or url,
            "formats": formats,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def find_downloaded_file(folder: str):
    files = [
        Path(p) for p in glob.glob(os.path.join(folder, "*"))
        if os.path.isfile(p)
    ]
    if not files:
        return None

    media_exts = {".mp4", ".webm", ".m4a", ".mp3", ".opus", ".mov", ".mkv"}
    media = [p for p in files if p.suffix.lower() in media_exts]
    candidates = media or files
    return max(candidates, key=lambda p: p.stat().st_mtime)


@app.get("/download")
def download_video(url: str, format_id: str):
    url = validate_url(url)
    format_id = (format_id or "").strip()
    if not format_id:
        raise HTTPException(status_code=400, detail="format_id is required")

    temp_dir = tempfile.mkdtemp(prefix="xmedia_")
    output_template = os.path.join(temp_dir, "%(title).120s.%(ext)s")

    ydl_opts = get_common_ydl_opts()
    ydl_opts.update({
        "socket_timeout": 60,
        "retries": 5,
        "format": f"{format_id}+bestaudio/best",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
    })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        file_path = find_downloaded_file(temp_dir)
        if not file_path:
            raise HTTPException(
                status_code=500, detail="Download completed but output file was not found"
            )

        title = info.get("title") or "download"
        safe_title = "".join(
            c for c in title if c.isalnum() or c in " ._-()"
        ).strip() or "download"

        ext = file_path.suffix.lower().lstrip(".") or "mp4"
        filename = f"{safe_title}.{ext}"

        media_type = {
            "mp4": "video/mp4",
            "webm": "video/webm",
            "mkv": "video/x-matroska",
            "mov": "video/quicktime",
            "m4a": "audio/mp4",
            "mp3": "audio/mpeg",
            "opus": "audio/ogg",
        }.get(ext, "application/octet-stream")

        background_tasks = BackgroundTasks()
        background_tasks.add_task(shutil.rmtree, temp_dir, ignore_errors=True)

        return FileResponse(
            path=str(file_path),
            media_type=media_type,
            filename=filename,
            background=background_tasks,
        )

    except HTTPException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
