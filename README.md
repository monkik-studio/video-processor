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

1. Install FFmpeg, or use the bundled `imageio-ffmpeg` fallback installed from `requirements.txt`:

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
   flask --app app run --host 0.0.0.0 --port 5000 --debug
   ```

4. Open `http://127.0.0.1:5000`.

## Environment Variables

- `SECRET_KEY`: Flask session secret. Set this in production.
- `MAX_UPLOAD_MB`: Upload limit in MB. Default: `2048`.
- `FILE_TTL_HOURS`: Hours before uploaded and generated video files are deleted. Default: `24`.
- `PORT`: Port used by `python app.py` or Render.
- `STORAGE_DIR`: Base directory for production uploads and outputs. Default: project directory.
- `UPLOAD_DIR`: Optional explicit upload directory. Overrides `STORAGE_DIR/uploads`.
- `OUTPUT_DIR`: Optional explicit output directory. Overrides `STORAGE_DIR/outputs`.
- `FFMPEG_PATH`: Optional explicit path to an FFmpeg binary.
- `FFPROBE_PATH`: Optional explicit path to an FFprobe binary.
- `FLASK_DEBUG`: Set to `1` only for local debugging when running `python app.py`.

Example:

```bash
export SECRET_KEY="replace-with-a-long-random-value"
export MAX_UPLOAD_MB=2048
export FILE_TTL_HOURS=24
export STORAGE_DIR=/var/data
```

## Deploy on Render

1. Push this project to GitHub.
2. Create a new Render Web Service.
3. Use these native Python settings:
   - Runtime: Python
   - Python version: from `runtime.txt`
   - Build command: `pip install -r requirements.txt`
   - Start command: Render can use the included `Procfile`, or set `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 1800 --workers 1`
4. Add environment variables:
   - `SECRET_KEY`
   - `MAX_UPLOAD_MB=2048`
   - `FILE_TTL_HOURS=24`
   - `STORAGE_DIR=/var/data` if you attach a Render disk at `/var/data`
5. Add a Render disk for production video files:
   - Mount path: `/var/data`
   - Set `STORAGE_DIR=/var/data`
   - The app will create `/var/data/uploads` and `/var/data/outputs`
6. FFmpeg support:
   - Native Python deploys use the `imageio-ffmpeg` package in `requirements.txt` as a bundled FFmpeg fallback.
   - If you prefer system FFmpeg and FFprobe, set `FFMPEG_PATH` and `FFPROBE_PATH` or make both available on PATH.
   - The included `Dockerfile` installs system FFmpeg and also binds Gunicorn to Render's `PORT`.

Render's default filesystem can be ephemeral. For production, attach a disk or move uploads/outputs to object storage. Keep `FILE_TTL_HOURS` enabled so temporary videos and ZIP files are cleaned automatically.

## Notes

- Large 2GB uploads require compatible proxy/server limits in front of Flask.
- Background music replaces the original audio track. If no music is uploaded and mute is off, the original audio is preserved when present.
- Trim times accept `MM:SS` or `HH:MM:SS`.
