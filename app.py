import csv
import json
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", BASE_DIR)).resolve()
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", STORAGE_DIR / "uploads")).resolve()
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", STORAGE_DIR / "outputs")).resolve()
METADATA_JSON = OUTPUT_DIR / "metadata.json"
METADATA_CSV = OUTPUT_DIR / "metadata.csv"

VIDEO_EXTENSIONS = {".mp4", ".mov"}
LOGO_EXTENSIONS = {".png"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}

OUTPUT_FORMATS = {
    "youtube": {"label": "YouTube", "width": 1920, "height": 1080, "ratio": "16:9"},
    "vertical": {"label": "TikTok / Reels", "width": 1080, "height": 1920, "ratio": "9:16"},
    "square": {"label": "Square", "width": 1080, "height": 1080, "ratio": "1:1"},
}

TEXT_POSITIONS = {
    "top": "y=h*0.09",
    "center": "y=(h-text_h)/2",
    "bottom": "y=h-text_h-h*0.1",
}

LOGO_POSITIONS = {
    "top-right": "x=main_w-overlay_w-40:y=40",
    "bottom-right": "x=main_w-overlay_w-40:y=main_h-overlay_h-40",
}

YOUTUBE_METADATA_TEMPLATES = {
    "property": {
        "fallback_title": "Luxury Property Video Tour",
        "title_suffix": "Property Tour",
        "description": (
            "Take a polished video tour of this property, including standout spaces, "
            "lifestyle details, and visual highlights designed for buyers, renters, "
            "and real estate audiences."
        ),
        "keywords": [
            "property tour",
            "real estate video",
            "luxury home",
            "home tour",
            "property listing",
            "real estate marketing",
            "interior design",
            "dream home",
            "house tour",
            "architecture",
        ],
        "hashtags": "#PropertyTour #RealEstate #HomeTour",
    },
    "boating": {
        "fallback_title": "Boating Lifestyle Video",
        "title_suffix": "Boating Video",
        "description": (
            "Enjoy a clean boating edit featuring time on the water, vessel details, "
            "coastal scenery, and lifestyle moments for marine and adventure audiences."
        ),
        "keywords": [
            "boating",
            "boat video",
            "yacht lifestyle",
            "marine video",
            "ocean adventure",
            "boat tour",
            "coastal lifestyle",
            "water sports",
            "sailing",
            "luxury boating",
        ],
        "hashtags": "#Boating #BoatLife #OceanLifestyle",
    },
    "surfing": {
        "fallback_title": "Surfing Highlight Video",
        "title_suffix": "Surfing Highlights",
        "description": (
            "Watch a crisp surfing edit with wave action, beach energy, and ocean "
            "moments shaped for surf fans, travel viewers, and action-sports channels."
        ),
        "keywords": [
            "surfing",
            "surf video",
            "wave riding",
            "surf highlights",
            "beach lifestyle",
            "ocean waves",
            "surf session",
            "action sports",
            "surf travel",
            "coastal adventure",
        ],
        "hashtags": "#Surfing #SurfLife #OceanWaves",
    },
}


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-change-me")
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "2048")) * 1024 * 1024
    app.config["UPLOAD_FOLDER"] = UPLOAD_DIR
    app.config["OUTPUT_FOLDER"] = OUTPUT_DIR
    app.config["FILE_TTL_HOURS"] = int(os.getenv("FILE_TTL_HOURS", "24"))

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    @app.before_request
    def clean_old_files():
        cleanup_files(app.config["FILE_TTL_HOURS"])

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(_error):
        flash("That file is too large. The maximum upload size is 2GB by default.", "danger")
        return redirect(url_for("index"))

    @app.route("/", methods=["GET"])
    def index():
        return render_template("index.html", formats=OUTPUT_FORMATS)

    @app.route("/upload", methods=["POST"])
    def upload():
        videos = [file for file in request.files.getlist("video") if file and file.filename]
        if not videos:
            flash("Choose one or more MP4 or MOV videos first.", "warning")
            return redirect(url_for("index"))

        uploaded_videos = []
        for video in videos:
            original_name = secure_filename(video.filename)
            if not allowed_extension(original_name, VIDEO_EXTENSIONS):
                flash(f"{original_name} is not supported. Only MP4 and MOV videos are allowed.", "danger")
                continue

            file_id = uuid.uuid4().hex
            upload_name = f"{file_id}_{original_name}"
            upload_path = UPLOAD_DIR / upload_name
            video.save(upload_path)

            try:
                info = probe_video(upload_path)
            except RuntimeError as exc:
                upload_path.unlink(missing_ok=True)
                flash(f"{original_name}: {exc}", "danger")
                continue

            uploaded_videos.append(
                {
                    "file_id": file_id,
                    "filename": upload_name,
                    "original_name": original_name,
                    "info": info,
                }
            )

        if not uploaded_videos:
            flash("No valid videos could be analyzed.", "danger")
            return redirect(url_for("index"))

        return render_template(
            "process.html",
            videos=uploaded_videos,
            formats=OUTPUT_FORMATS,
        )

    @app.route("/process", methods=["POST"])
    def process():
        filename = request.form.get("filename", "")
        source_path = safe_child_path(UPLOAD_DIR, filename)
        if not source_path or not source_path.exists():
            abort(404)

        output_format = request.form.get("output_format", "youtube")
        if output_format not in OUTPUT_FORMATS:
            abort(400, "Unknown output format")

        title = request.form.get("title", "").strip()
        text_position = request.form.get("text_position", "bottom")
        logo_position = request.form.get("logo_position", "bottom-right")
        category = request.form.get("category", "property")
        trim_start = request.form.get("trim_start", "").strip()
        trim_end = request.form.get("trim_end", "").strip()
        mute_audio = request.form.get("mute_audio") == "on"

        file_id = uuid.uuid4().hex
        output_name = f"{file_id}_{Path(filename).stem}_{output_format}.mp4"
        output_path = OUTPUT_DIR / output_name
        logo_path = None
        music_path = None

        try:
            logo_path = save_optional_upload("logo", LOGO_EXTENSIONS)
            music_path = save_optional_upload("music", AUDIO_EXTENSIONS)
            command = build_ffmpeg_command(
                source_path=source_path,
                output_path=output_path,
                output_format=output_format,
                title=title,
                text_position=text_position,
                logo_path=logo_path,
                logo_position=logo_position,
                music_path=music_path,
                mute_audio=mute_audio,
                trim_start=trim_start,
                trim_end=trim_end,
            )
            run_ffmpeg(command)
            info = probe_video(output_path)
            metadata = append_metadata(
                filename=output_name,
                duration=info["duration"],
                resolution=info["resolution"],
                output_format=OUTPUT_FORMATS[output_format]["label"],
                category=category,
            )
            youtube_metadata = generate_youtube_metadata(
                category=category,
                title=title,
                output_format=OUTPUT_FORMATS[output_format]["label"],
                duration_label=info["duration_label"],
            )
        except RuntimeError as exc:
            output_path.unlink(missing_ok=True)
            return jsonify({"ok": False, "error": str(exc)}), 500
        finally:
            if logo_path:
                logo_path.unlink(missing_ok=True)
            if music_path:
                music_path.unlink(missing_ok=True)

        return jsonify(
            {
                "ok": True,
                "filename": output_name,
                "preview_url": url_for("output_file", filename=output_name),
                "download_url": url_for("download_file", filename=output_name),
                "metadata": metadata,
                "youtube_metadata": youtube_metadata,
            }
        )

    @app.route("/zip", methods=["POST"])
    def create_zip():
        data = request.get_json(silent=True) or {}
        filenames = data.get("filenames", [])
        if not isinstance(filenames, list) or not filenames:
            return jsonify({"ok": False, "error": "No output files were provided."}), 400

        zip_name = f"{uuid.uuid4().hex}_video_exports.zip"
        zip_path = OUTPUT_DIR / zip_name
        metadata_records = []
        valid_count = 0

        try:
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for filename in filenames:
                    output_path = safe_child_path(OUTPUT_DIR, str(filename))
                    if not output_path or not output_path.exists() or output_path.suffix.lower() != ".mp4":
                        continue
                    valid_count += 1
                    archive.write(output_path, arcname=output_path.name)
                    try:
                        info = probe_video(output_path)
                        info["filename"] = output_path.name
                        metadata_records.append(info)
                    except RuntimeError:
                        metadata_records.append({"filename": output_path.name})

                if valid_count == 0:
                    raise RuntimeError("No valid output files were found.")

                archive.writestr(
                    "batch-summary.json",
                    json.dumps(
                        {
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "files": list(filenames),
                            "video_info": metadata_records,
                        },
                        indent=2,
                    ),
                )
        except (OSError, RuntimeError) as exc:
            zip_path.unlink(missing_ok=True)
            return jsonify({"ok": False, "error": f"Could not create ZIP file: {exc}"}), 500

        return jsonify(
            {
                "ok": True,
                "zip_url": url_for("download_file", filename=zip_name),
                "zip_filename": zip_name,
            }
        )

    @app.route("/outputs/<path:filename>")
    def output_file(filename):
        return send_from_directory(OUTPUT_DIR, filename)

    @app.route("/download/<path:filename>")
    def download_file(filename):
        return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)

    @app.route("/healthz")
    def healthz():
        return {"ok": True}

    return app


def allowed_extension(filename, extensions):
    return Path(filename).suffix.lower() in extensions


def safe_child_path(directory, filename):
    candidate = (directory / filename).resolve()
    try:
        candidate.relative_to(directory.resolve())
    except ValueError:
        return None
    return candidate


def save_optional_upload(field, extensions):
    uploaded = request.files.get(field)
    if not uploaded or not uploaded.filename:
        return None
    original = secure_filename(uploaded.filename)
    if not allowed_extension(original, extensions):
        raise RuntimeError(f"Unsupported {field} file type.")
    path = UPLOAD_DIR / f"{uuid.uuid4().hex}_{original}"
    uploaded.save(path)
    return path


def ensure_ffmpeg_available():
    if not get_ffmpeg_path():
        raise RuntimeError("FFmpeg must be installed and available on PATH or through imageio-ffmpeg.")


def probe_video(path):
    ensure_ffmpeg_available()
    ffprobe_path = get_ffprobe_path()
    if ffprobe_path:
        command = [
            ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,duration",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError("Could not read video details. Please upload a valid MP4 or MOV file.")

        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]
        fmt = data.get("format", {})
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        duration = float(stream.get("duration") or fmt.get("duration") or 0)
        size = int(fmt.get("size") or path.stat().st_size)
        fps = parse_fps(stream.get("r_frame_rate", "0/1"))
    else:
        width, height, duration, fps = probe_video_with_ffmpeg(path)
        size = path.stat().st_size

    return {
        "duration": round(duration, 2),
        "duration_label": format_duration(duration),
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}",
        "fps": round(fps, 2),
        "file_size": size,
        "file_size_label": format_bytes(size),
    }


def has_audio_stream(path):
    ffprobe_path = get_ffprobe_path()
    if not ffprobe_path:
        return has_audio_stream_with_ffmpeg(path)

    command = [
        ffprobe_path,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.returncode == 0 and bool(result.stdout.strip())


def get_ffmpeg_path():
    if os.getenv("FFMPEG_PATH"):
        return os.getenv("FFMPEG_PATH")
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def get_ffprobe_path():
    if os.getenv("FFPROBE_PATH"):
        return os.getenv("FFPROBE_PATH")
    return shutil.which("ffprobe")


def probe_video_with_ffmpeg(path):
    command = [get_ffmpeg_path(), "-hide_banner", "-i", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    details = f"{result.stderr}\n{result.stdout}"
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", details)
    resolution_match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", details)
    fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", details)

    if not duration_match or not resolution_match:
        raise RuntimeError("Could not read video details. Please upload a valid MP4 or MOV file.")

    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    width, height = resolution_match.groups()
    fps = float(fps_match.group(1)) if fps_match else 0
    return int(width), int(height), duration, fps


def has_audio_stream_with_ffmpeg(path):
    command = [get_ffmpeg_path(), "-hide_banner", "-i", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    details = f"{result.stderr}\n{result.stdout}"
    return bool(re.search(r"Stream #.*Audio:", details))


def parse_fps(value):
    try:
        numerator, denominator = value.split("/")
        denominator = float(denominator)
        return float(numerator) / denominator if denominator else 0
    except (ValueError, ZeroDivisionError):
        return 0


def format_duration(seconds):
    seconds = max(0, int(round(seconds)))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def format_bytes(size):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def validate_time(value):
    if not value:
        return None
    parts = value.split(":")
    if len(parts) not in (2, 3):
        raise RuntimeError("Trim times must use MM:SS or HH:MM:SS.")
    if not all(part.isdigit() for part in parts):
        raise RuntimeError("Trim times must contain numbers only.")
    return value


def escape_drawtext(text):
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace("\n", " ")
    )


def generate_youtube_metadata(category, title, output_format, duration_label):
    template = YOUTUBE_METADATA_TEMPLATES.get(category, YOUTUBE_METADATA_TEMPLATES["property"])
    clean_title = " ".join(title.split()) if title else template["fallback_title"]
    suffix = template["title_suffix"]
    youtube_title = clean_title if suffix.lower() in clean_title.lower() else f"{clean_title} | {suffix}"

    description = (
        f"{template['description']}\n\n"
        f"Format: {output_format}\n"
        f"Duration: {duration_label}\n"
        f"Category: {category.title()}\n\n"
        "Created with a clean, social-ready video export workflow.\n\n"
        f"{template['hashtags']}"
    )

    keywords = template["keywords"][:]
    if title:
        keywords.insert(0, clean_title.lower())

    return {
        "title": youtube_title[:100],
        "description": description,
        "keywords": ", ".join(dict.fromkeys(keywords)),
    }


def build_ffmpeg_command(
    source_path,
    output_path,
    output_format,
    title,
    text_position,
    logo_path,
    logo_position,
    music_path,
    mute_audio,
    trim_start,
    trim_end,
):
    ensure_ffmpeg_available()
    spec = OUTPUT_FORMATS[output_format]
    width = spec["width"]
    height = spec["height"]
    text_y = TEXT_POSITIONS.get(text_position, TEXT_POSITIONS["bottom"])
    logo_overlay = LOGO_POSITIONS.get(logo_position, LOGO_POSITIONS["bottom-right"])
    trim_start = validate_time(trim_start)
    trim_end = validate_time(trim_end)

    command = [
        get_ffmpeg_path(),
        "-y",
        "-hide_banner",
        "-filter_threads",
        "1",
        "-filter_complex_threads",
        "1",
    ]
    if trim_start:
        command.extend(["-ss", trim_start])
    if trim_end:
        command.extend(["-to", trim_end])

    command.extend(["-i", str(source_path)])
    input_index = 1
    logo_index = None
    music_index = None

    if logo_path:
        logo_index = input_index
        input_index += 1
        command.extend(["-i", str(logo_path)])

    if music_path:
        music_index = input_index
        command.extend(["-stream_loop", "-1", "-i", str(music_path)])

    filters = [
        f"[0:v]fps=30,scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1[base]"
    ]
    current = "base"

    if title:
        escaped = escape_drawtext(title)
        filters.append(
            f"[{current}]drawtext=text='{escaped}':"
            "fontcolor=white:fontsize=h/18:line_spacing=10:"
            "borderw=3:bordercolor=black@0.45:shadowcolor=black@0.65:"
            "shadowx=3:shadowy=3:"
            f"x=(w-text_w)/2:{text_y}[texted]"
        )
        current = "texted"

    if logo_index is not None:
        filters.append(
            f"[{logo_index}:v]scale='min(220,iw)':'-1'[logo];"
            f"[{current}][logo]overlay={logo_overlay}[vout]"
        )
        current = "vout"

    audio_output = None
    if music_index is not None and not mute_audio and has_audio_stream(source_path):
        filters.append(
            f"[0:a:0]volume=1.0[original_audio];"
            f"[{music_index}:a:0]volume=0.28[music_audio];"
            "[original_audio][music_audio]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        audio_output = "[aout]"

    filter_complex = ";".join(filters)
    command.extend(["-filter_complex", filter_complex, "-map", f"[{current}]"])

    if audio_output:
        command.extend(["-map", audio_output])
    elif music_index is not None:
        command.extend(["-map", f"{music_index}:a:0", "-shortest"])
    elif mute_audio:
        command.append("-an")
    else:
        command.extend(["-map", "0:a?", "-c:a", "aac", "-b:a", "192k"])

    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
        ]
    )

    if music_index is not None:
        command.extend(["-c:a", "aac", "-b:a", "192k"])

    command.append(str(output_path))
    return command


def run_ffmpeg(command):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = result.stderr.strip().splitlines()[-1] if result.stderr else "FFmpeg failed."
        raise RuntimeError(f"Video processing failed: {message}")


def append_metadata(filename, duration, resolution, output_format, category):
    record = {
        "filename": filename,
        "duration": duration,
        "resolution": resolution,
        "format": output_format,
        "category": category,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    records = []
    if METADATA_JSON.exists():
        try:
            records = json.loads(METADATA_JSON.read_text())
        except json.JSONDecodeError:
            records = []
    records.append(record)
    METADATA_JSON.write_text(json.dumps(records, indent=2))

    csv_exists = METADATA_CSV.exists()
    with METADATA_CSV.open("a", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=record.keys())
        if not csv_exists:
            writer.writeheader()
        writer.writerow(record)

    return record


def cleanup_files(ttl_hours):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    for directory in (UPLOAD_DIR, OUTPUT_DIR):
        if not directory.exists():
            continue
        for path in directory.iterdir():
            if path.name in {"metadata.json", "metadata.csv"} or not path.is_file():
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if modified < cutoff:
                path.unlink(missing_ok=True)


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
