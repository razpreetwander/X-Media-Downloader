# ============================================================
# MUSIC
# Uses the EXACT SAME YouTube system above
# ============================================================

@app.get("/music/info")
def music_info(
    url: str = Query(..., description="YouTube Music / YouTube URL")
):
    # Same exact YouTube /info response
    return get_info(url=url)


@app.get("/music/download")
def music_download(
    url: str = Query(...),
    format_id: str = Query(default=None)
):
    # Same exact YouTube /download system
    return download_stream(
        url=url,
        format_id=format_id
    )


# Optional short aliases
@app.get("/audio/info")
def audio_info(
    url: str = Query(...)
):
    return get_info(url=url)


@app.get("/audio/download")
def audio_download(
    url: str = Query(...),
    format_id: str = Query(default=None)
):
    return download_stream(
        url=url,
        format_id=format_id
    )