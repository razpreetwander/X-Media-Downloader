# X Media Downloader Backend — fixed

This backend includes:
- FastAPI CORS middleware (including `Origin: null`)
- GET `/info?url=...`
- GET `/download?url=...&format_id=...`
- `/health` endpoint
- yt-dlp based extraction/download
- temporary output cleanup

Deploy these files to the Render service used by the frontend.
