import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import yt_dlp

app = FastAPI()

@app.get("/")
def home():
    return {"status": "Universal Downloader Engine is Active!"}

@app.get("/info")
def get_info(url: str):
    try:
        ydl_opts = {'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            for f in info.get('formats', []):
                if f.get('ext') in ['mp4', 'webm']:
                    formats.append({
                        "format_id": f.get('format_id'),
                        "resolution": f.get('resolution') or f.get('format_note'),
                        "ext": f.get('ext')
                    })
            return {
                "title": info.get('title'),
                "thumbnail": info.get('thumbnail'),
                "formats": formats
            }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/download")
def download_video(url: str, format_id: str):
    try:
        output_template = "downloaded_video.%(ext)s"
        ydl_opts = {
            'format': f'{format_id}+bestaudio/best' if format_id else 'best',
            'outtmpl': output_template,
            'merge_output_format': 'mp4',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if not os.path.exists(filename):
                filename = os.path.splitext(filename)[0] + ".mp4"

        return FileResponse(filename, media_type="video/mp4", filename="video.mp4")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
