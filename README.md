# Video Format Studio

A production-ready Flask application for processing property, boating, and surfing videos with FFmpeg.

## Features

- Upload MP4 or MOV files up to 2GB by default
- Batch upload and process multiple videos with the same export settings
- Inspect duration, resolution, FPS, and file size
- Export to YouTube 16:9, TikTok/Reels 9:16, or square 1:1
- Crop and resize without stretching
- Optional trim, mute original audio, and background music
- Modern white text overlay with shadow
- Optional PNG logo watermark
- H.264 MP4 output with faststart for web preview
- Template-based YouTube title, description, and keyword generation
- ZIP download for completed batch exports
- JSON and CSV metadata export in `outputs/`
- Automatic cleanup of old upload/output files

## Local Run

1. Install FFmpeg:

   ```bash
   brew install ffmpeg
   ```

2. Create a virtual environment and install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Run the app:

   ```bash
   flask --app app run --debug
   ```

4. Open `http://127.0.0.1:5000`.

## Environment Variables

- `SECRET_KEY`: Flask session secret. Set this in production.
- `MAX_UPLOAD_MB`: Upload limit in MB. Default: `2048`.
- `FILE_TTL_HOURS`: Hours before uploaded and generated video files are deleted. Default: `24`.
- `PORT`: Port used by `python app.py` or Render.

Example:

```bash
export SECRET_KEY="replace-with-a-long-random-value"
export MAX_UPLOAD_MB=2048
export FILE_TTL_HOURS=24
```

## Deploy on Render

1. Push this project to GitHub.
2. Create a new Render Web Service.
3. Use these settings:
   - Runtime: Python
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app --timeout 1800`
4. Add environment variables:
   - `SECRET_KEY`
   - `MAX_UPLOAD_MB=2048`
   - `FILE_TTL_HOURS=24`
5. Add FFmpeg support. This project includes a `Dockerfile` that installs FFmpeg, so the most reliable Render setup is to deploy it as a Docker web service. If you use Render's native Python runtime instead, confirm `ffmpeg` and `ffprobe` are available on PATH.

For persistent production storage, attach a disk or move uploads/outputs to object storage. Render's default filesystem can be ephemeral.

## Notes

- Large 2GB uploads require compatible proxy/server limits in front of Flask.
- Background music replaces the original audio track. If no music is uploaded and mute is off, the original audio is preserved when present.
- Trim times accept `MM:SS` or `HH:MM:SS`.
