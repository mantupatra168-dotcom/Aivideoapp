#!/usr/bin/env python3
"""
AiVantu Phase-3 - Production-ready single-file Flask backend (API-only).

Features included:
- SQLite by default (Postgres optional via DATABASE_URL)
- Uploads (images/audio/music) saved under ./uploads
- Outputs under ./outputs (movie files)
- TTS preview (gTTS), per-character TTS generation
- MoviePy renderer (naive lip-sync-like effect)
- DB models: UserProfile, UserCharacter, UserVideo, TemplateCatalog, VoiceOption, Plan
- Endpoints: /, /health, /profile, /upload, /preview_voice, /generate_video, /gallery, /admin/status
- Robust logging and guarded optional imports
- Graceful error responses (JSON)
- Avoids any render_template / HTML rendering (API-only) so "templates missing" errors won't occur.

Notes:
- ffmpeg must be installed on the host (moviepy uses it).
- For heavy loads put rendering into a background queue (RQ / Celery).
- If you plan Postgres on Render/AWS/GCP, set DATABASE_URL env var. If not, SQLite used.
"""

import os
import uuid
import json
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from flask import Flask, request, jsonify, url_for, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aivantu")

# ---------- Paths ----------
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
OUTPUT_FOLDER = BASE_DIR / "outputs"
TMP_FOLDER = BASE_DIR / "tmp"
for p in (UPLOAD_FOLDER, OUTPUT_FOLDER, TMP_FOLDER):
    p.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_AUDIO_EXT = {"mp3", "wav", "ogg", "m4a"}
ALLOWED_VIDEO_EXT = {"mp4", "mov", "mkv", "webm"}

# ---------- App & DB ----------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("APP_SECRET_KEY", "aivantu-secret")
# DATABASE_URL optional (Postgres) - fallback to SQLite for free-plan compatibility
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", f"sqlite:///{str(BASE_DIR/'data.db')}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["OUTPUT_FOLDER"] = str(OUTPUT_FOLDER)
app.config["TMP_FOLDER"] = str(TMP_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", 700)) * 1024 * 1024

db = SQLAlchemy(app)

# ---------- Optional imports handled safely ----------
try:
    import moviepy  # type: ignore
    from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip, CompositeAudioClip
    from moviepy.video.fx.all import resize
    MOVIEPY_AVAILABLE = True
except Exception as e:
    log.warning("moviepy unavailable or import failed: %s", e)
    MOVIEPY_AVAILABLE = False

try:
    from gtts import gTTS  # type: ignore
    GTTS_AVAILABLE = True
except Exception:
    log.warning("gTTS not available - preview and TTS endpoints will fail")
    GTTS_AVAILABLE = False

# psycopg2 can cause binary build issues on some hosts; keep optional
try:
    import psycopg2  # pragma: no cover
    PSYCOPG2_AVAILABLE = True
except Exception:
    PSYCOPG2_AVAILABLE = False

# ---------- DB Models ----------
class UserProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(100))
    country = db.Column(db.String(100))
    photo = db.Column(db.String(1024))
    plan = db.Column(db.String(50), default="Free")
    credits = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UserCharacter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(255))
    name = db.Column(db.String(100))
    photo_path = db.Column(db.String(1024))
    voice_path = db.Column(db.String(1024))
    ai_style = db.Column(db.String(50))
    mood = db.Column(db.String(50))
    is_locked = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UserVideo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(255))
    title = db.Column(db.String(255))
    script = db.Column(db.Text)
    template = db.Column(db.String(255))
    voices = db.Column(db.String(255))
    quality = db.Column(db.String(20))
    length_type = db.Column(db.String(20))
    background_music = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    file_path = db.Column(db.String(1024))
    status = db.Column(db.String(50), default="ready")
    meta_json = db.Column(db.Text)

class TemplateCatalog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255))
    category = db.Column(db.String(100))
    thumbnail = db.Column(db.String(1024))

class VoiceOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(255))
    description = db.Column(db.String(512))

class Plan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    price = db.Column(db.String(50))
    features = db.Column(db.String(255))

# ---------- DB init / defaults ----------
with app.app_context():
    db.create_all()
    # seed some data if empty
    if not VoiceOption.query.first():
        db.session.add_all([
            VoiceOption(display_name="Female", description="Soft female voice"),
            VoiceOption(display_name="Male", description="Deep male voice"),
            VoiceOption(display_name="Child", description="Child voice"),
            VoiceOption(display_name="Neutral", description="Neutral voice")
        ])
    if not TemplateCatalog.query.first():
        db.session.add_all([
            TemplateCatalog(name="Motivation", category="Inspiration"),
            TemplateCatalog(name="Promo", category="Marketing"),
            TemplateCatalog(name="Explainer", category="Education"),
        ])
    if not Plan.query.first():
        db.session.add_all([
            Plan(name="Free", price="0", features="Low quality, 1 render/day"),
            Plan(name="Premium", price="499", features="FullHD, 10 renders/day"),
        ])
    if not UserProfile.query.filter_by(email="demo@aivantu.com").first():
        db.session.add(UserProfile(email="demo@aivantu.com", name="Demo User", country="India", credits=5))
    db.session.commit()

# ---------- Helpers ----------
def allowed_file(filename: str, allowed_set: set) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_set

def save_upload(file_storage, subfolder: str = "") -> str:
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
    uid = uuid.uuid4().hex
    dest_name = f"{uid}.{ext}" if ext else uid
    folder = Path(app.config["UPLOAD_FOLDER"]) / subfolder
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / dest_name
    file_storage.save(dest)
    rel = str(dest.relative_to(BASE_DIR))
    log.info("Saved upload: %s", rel)
    return rel

def _abs_path(rel_or_abs: str) -> str:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = BASE_DIR / rel_or_abs
    return str(p.resolve())

# lightweight lip-sync-like clip (alternates small zooms)
def create_lip_sync_like_clip(image_path: str, duration: float, size_width: int = 1280):
    if not MOVIEPY_AVAILABLE:
        raise RuntimeError("MoviePy not available on this environment")
    abs_img = _abs_path(image_path)
    base = ImageClip(abs_img).set_duration(duration).resize(width=size_width)
    small = base.fx(resize, 0.98)
    seg = 0.12
    clips = []
    t = 0.0
    toggle = False
    while t < duration - 1e-6:
        seg_d = min(seg, duration - t)
        clip = small.set_duration(seg_d) if toggle else base.set_duration(seg_d)
        clips.append(clip)
        toggle = not toggle
        t += seg_d
    return concatenate_videoclips(clips, method="compose")

def render_video_multi_characters(image_rel_paths: List[str], audio_rel_paths: List[str],
                                  output_abs_path: str, quality: str = "HD",
                                  bg_music_rel: Optional[str] = None):
    if not MOVIEPY_AVAILABLE:
        raise RuntimeError("MoviePy not available for rendering")
    clips = []
    audios = []
    n = min(len(image_rel_paths), len(audio_rel_paths))
    if n == 0:
        raise ValueError("No character images or audios provided")
    for i in range(n):
        img = image_rel_paths[i]
        aud = audio_rel_paths[i]
        audio_abs = _abs_path(aud)
        audio_clip = AudioFileClip(audio_abs)
        audios.append(audio_clip)
        dur = audio_clip.duration if audio_clip.duration > 0.1 else 2.0
        clip = create_lip_sync_like_clip(img, dur)
        clip = clip.set_audio(audio_clip)
        clips.append(clip)
    final_video = concatenate_videoclips(clips, method="compose")
    if bg_music_rel:
        try:
            bg_abs = _abs_path(bg_music_rel)
            bg_clip = AudioFileClip(bg_abs)
            if bg_clip.duration < final_video.duration:
                from moviepy.editor import concatenate_audioclips
                n_loops = int(final_video.duration / bg_clip.duration) + 1
                bg_parts = [bg_clip] * n_loops
                bg_clip = concatenate_audioclips(bg_parts).subclip(0, final_video.duration)
            else:
                bg_clip = bg_clip.subclip(0, final_video.duration)
            bg_clip = bg_clip.volumex(0.12)
            final_audio = CompositeAudioClip([final_video.audio, bg_clip])
            final_video = final_video.set_audio(final_audio)
        except Exception as e:
            log.exception("Failed to load bg music: %s", e)
    bitrate = "800k"
    if quality and quality.lower() in ("fullhd", "1080", "1080p"):
        bitrate = "2500k"
    if quality and quality.lower() in ("4k", "2160", "2160p"):
        bitrate = "8000k"
    final_video.write_videofile(output_abs_path, fps=24, codec="libx264", audio_codec="aac", bitrate=bitrate)
    final_video.close()
    for a in audios:
        try:
            a.close()
        except Exception:
            pass

# ---------- Routes ----------
@app.route("/", methods=["GET"])
def index():
    return jsonify({"msg": "AiVantu Phase-3 backend running", "status": "ok"})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "moviepy": MOVIEPY_AVAILABLE,
        "gtts": GTTS_AVAILABLE,
        "psycopg2": PSYCOPG2_AVAILABLE,
        "db": app.config["SQLALCHEMY_DATABASE_URI"]
    })

# serve uploads & outputs
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/outputs/<path:filename>")
def output_file(filename):
    return send_from_directory(app.config["OUTPUT_FOLDER"], filename)

# Profile & basic CRUD
@app.route("/profile/<string:email>", methods=["GET"])
def get_profile(email):
    user = UserProfile.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "email": user.email, "name": user.name, "country": user.country,
        "plan": user.plan, "credits": user.credits, "photo": user.photo
    })

@app.route("/profile", methods=["POST"])
def upsert_profile():
    data = request.get_json(force=True)
    email = data.get("email")
    if not email:
        return jsonify({"error": "email required"}), 400
    user = UserProfile.query.filter_by(email=email).first()
    if not user:
        user = UserProfile(email=email, name=data.get("name"), country=data.get("country"))
        db.session.add(user)
    else:
        user.name = data.get("name", user.name)
        user.country = data.get("country", user.country)
    db.session.commit()
    return jsonify({"message": "ok", "email": user.email})

# Upload endpoint for images/audio/music
@app.route("/upload", methods=["POST"])
def upload_endpoint():
    kind = request.form.get("kind", "file")
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    f = request.files["file"]
    if not f or f.filename == "":
        return jsonify({"error": "invalid file"}), 400
    # choose allowed set by form param
    allowed = ALLOWED_IMAGE_EXT.union(ALLOWED_AUDIO_EXT)
    saved = save_upload(f, kind)
    return jsonify({"saved": saved, "url": url_for("uploaded_file", filename=saved.replace("uploads/",""), _external=True)})

# preview voice (gTTS)
@app.route("/preview_voice", methods=["POST"])
def preview_voice():
    if not GTTS_AVAILABLE:
        return jsonify({"error": "gTTS not available on server"}), 500
    text = request.form.get("text", "Preview from AiVantu")
    lang = request.form.get("lang", "hi")
    try:
        uid = uuid.uuid4().hex
        out = Path(app.config["TMP_FOLDER"]) / f"preview_{uid}.mp3"
        tts = gTTS(text, lang=lang)
        tts.save(str(out))
        dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out), str(dest))
        return jsonify({"audio_rel": str(Path("audio")/dest.name),
                        "audio_url": url_for("uploaded_file", filename=str(Path("audio")/dest.name), _external=True)})
    except Exception as e:
        log.exception("Error generating preview voice")
        return jsonify({"error": "TTS failed", "details": str(e)}), 500

# generate multi-character video (synchronous - for tests). For prod use background worker.
@app.route("/generate_video", methods=["POST"])
def generate_video():
    """
    Form-data:
    - user_email
    - title
    - script
    - template
    - quality
    - length_type
    - lang
    - bg_music_file (file) OR bg_music preset name
    - characters[] (files)
    - character_voice_files[] (optional files)
    - voice_type[] optional
    """
    # basic params
    demo_user_email = request.form.get("user_email", "demo@aivantu.com")
    title = request.form.get("title") or f"Video {datetime.utcnow().isoformat()}"
    script = request.form.get("script", "") or ""
    template = request.form.get("template", "Default")
    quality = request.form.get("quality", "HD")
    lang = request.form.get("lang", "hi")
    bg_music_choice = request.form.get("bg_music", "")

    # create DB record early
    video = UserVideo(user_email=demo_user_email, title=title, script=script, template=template,
                      quality=quality, length_type=request.form.get("length_type","short"),
                      background_music=bg_music_choice, status="rendering")
    db.session.add(video)
    db.session.commit()
    job_id = f"video_{video.id}"
    log.info("Starting render job %s", job_id)

    # save character images
    image_rel_paths = []
    if "characters" in request.files:
        files = request.files.getlist("characters")
        for f in files:
            if f and allowed_file(f.filename, ALLOWED_IMAGE_EXT):
                image_rel_paths.append(save_upload(f, "characters"))

    # placeholder if no characters
    if not image_rel_paths:
        # try template thumbnail else create a blank placeholder
        tc = TemplateCatalog.query.filter_by(name=template).first()
        if tc and tc.thumbnail:
            image_rel_paths = [tc.thumbnail]
        else:
            try:
                from PIL import Image
                placeholder = Path(app.config["TMP_FOLDER"]) / f"{job_id}_ph.png"
                img = Image.new("RGB", (1280,720), color=(245,245,245))
                img.save(placeholder)
                image_rel_paths = [str(placeholder.relative_to(BASE_DIR))]
            except Exception as e:
                log.exception("Placeholder failed")
                video.status = "failed"
                db.session.commit()
                return jsonify({"status":"error","message":"no characters and placeholder failed","details":str(e)}), 400

    # background music file
    bg_music_rel = None
    if "bg_music_file" in request.files:
        f = request.files.get("bg_music_file")
        if f and allowed_file(f.filename, ALLOWED_AUDIO_EXT):
            bg_music_rel = save_upload(f, "music")
    else:
        if bg_music_choice:
            p = Path(app.config["UPLOAD_FOLDER"]) / "music" / f"{bg_music_choice}.mp3"
            if p.exists():
                bg_music_rel = str(Path("music")/p.name)

    # character custom voice files
    char_voice_files = []
    if "character_voice_files" in request.files:
        vfiles = request.files.getlist("character_voice_files")
        for vf in vfiles:
            if vf and allowed_file(vf.filename, ALLOWED_AUDIO_EXT):
                char_voice_files.append(save_upload(vf, "user_voices"))

    # voice types pad
    voice_types = request.form.getlist("voice_type")
    while len(voice_types) < len(image_rel_paths):
        voice_types.append(voice_types[0] if voice_types else "Female")

    # split script across characters (markers [C1:] etc or naive split)
    char_texts = []
    markers = [f"[C{i+1}]:" for i in range(len(image_rel_paths))]
    if any(m in script for m in markers):
        remaining = script
        for m in markers:
            idx = remaining.find(m)
            if idx == -1:
                char_texts.append("")
                continue
            # find next marker position
            nxt_positions = [remaining.find(x, idx+1) for x in markers if remaining.find(x, idx+1) != -1]
            next_pos = min(nxt_positions) if nxt_positions else len(remaining)
            part = remaining[idx+len(m):next_pos].strip()
            char_texts.append(part)
    else:
        # distribute by lines / sentences
        lines = [l.strip() for l in script.replace("\r","\n").split("\n") if l.strip()]
        if not lines:
            words = script.split()
            if not words:
                char_texts = ["Hello from AiVantu"] + [""]*(len(image_rel_paths)-1)
            else:
                per = max(1, len(words)//len(image_rel_paths))
                for i in range(len(image_rel_paths)):
                    part_words = words[i*per:(i+1)*per] if i < len(image_rel_paths)-1 else words[i*per:]
                    char_texts.append(" ".join(part_words).strip())
        else:
            char_texts = [""]*len(image_rel_paths)
            for idx, s in enumerate(lines):
                char_texts[idx % len(image_rel_paths)] += (s + " ")
            char_texts = [c.strip() for c in char_texts]

    while len(char_texts) < len(image_rel_paths):
        char_texts.append("")

    # Create audio files per character (prefer uploaded voice)
    audio_rel_paths = []
    for i in range(len(image_rel_paths)):
        if i < len(char_voice_files):
            audio_rel_paths.append(char_voice_files[i])
            continue
        text_for_char = char_texts[i] if i < len(char_texts) else ""
        if not text_for_char.strip():
            # create a short silent TTS using gTTS space (or empty file fallback)
            if GTTS_AVAILABLE:
                try:
                    out = Path(app.config["TMP_FOLDER"]) / f"{job_id}_empty_{i}.mp3"
                    gTTS(" ", lang=lang).save(str(out))
                    dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(out), str(dest))
                    audio_rel_paths.append(str(Path("audio")/dest.name))
                    continue
                except Exception:
                    pass
            # fallback empty file path
            p = Path(app.config["TMP_FOLDER"]) / f"{job_id}_silent_{i}.mp3"
            p.write_bytes(b"")
            audio_rel_paths.append(str(p.relative_to(BASE_DIR)))
            continue
        # normal TTS generation
        if not GTTS_AVAILABLE:
            video.status = "failed"
            db.session.commit()
            return jsonify({"status":"error","message":"gTTS not available to generate voices"}), 500
        try:
            uid = uuid.uuid4().hex
            out = Path(app.config["TMP_FOLDER"]) / f"{job_id}_{i}_{uid}.mp3"
            gTTS(text_for_char, lang=lang).save(str(out))
            dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(out), str(dest))
            audio_rel_paths.append(str(Path("audio")/dest.name))
        except Exception as e:
            log.exception("TTS generation failed for char %s: %s", i, e)
            video.status = "failed"
            db.session.commit()
            return jsonify({"status":"error","message":"TTS generation failed","details":str(e)}), 500

    # render video synchronously (test-only). In production, queue this job.
    out_name = f"video_{video.id}.mp4"
    out_abs = str(Path(app.config["OUTPUT_FOLDER"]) / out_name)
    try:
        render_video_multi_characters(image_rel_paths, audio_rel_paths, out_abs, quality=quality, bg_music_rel=bg_music_rel)
        video.file_path = str(Path("outputs") / out_name)
        video.status = "done"
        video.meta_json = json.dumps({
            "script": script,
            "characters": image_rel_paths,
            "voices": voice_types,
            "quality": quality,
            "created_at": datetime.utcnow().isoformat()
        })
        db.session.commit()
    except Exception as e:
        log.exception("Rendering failed: %s", e)
        video.status = "failed"
        db.session.commit()
        return jsonify({"status":"error","message":"render failed","details":str(e)}), 500

    return jsonify({"status":"done","video_id":video.id, "download_url": url_for("output_file", filename=out_name, _external=True)})

# gallery for a user
@app.route("/gallery/<string:user_email>", methods=["GET"])
def gallery(user_email):
    videos = UserVideo.query.filter_by(user_email=user_email).order_by(UserVideo.created_at.desc()).all()
    out = []
    for v in videos:
        out.append({
            "id": v.id,
            "title": v.title,
            "status": v.status,
            "file_path": v.file_path,
            "created_at": v.created_at.isoformat()
        })
    return jsonify({"videos": out})

# Admin status & simple controls
@app.route("/admin/status", methods=["GET"])
def admin_status():
    db_size = None
    try:
        db_path = Path(app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", ""))
        db_size = db_path.stat().st_size if db_path.exists() else None
    except Exception:
        db_size = None
    counts = {
        "users": UserProfile.query.count(),
        "videos": UserVideo.query.count(),
        "templates": TemplateCatalog.query.count(),
    }
    return jsonify({"ok": True, "counts": counts, "db_size": db_size})

# Payment placeholder endpoints (implement SDKs per provider)
@app.route("/payment/create_order", methods=["POST"])
def payment_create_order():
    data = request.get_json(force=True)
    # Example: client will send {"user_email": "...", "amount": 499, "provider": "razorpay"}
    # Implement provider SDK here. For now we return a placeholder.
    return jsonify({"status": "ok", "message": "Payment integration placeholder - implement provider SDK on server", "payload": data})

# ---------- Error handlers ----------
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "not found"}), 404

@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({"error": "file too large"}), 413

@app.errorhandler(Exception)
def all_exception(e):
    log.exception("Unhandled exception: %s", e)
    return jsonify({"error": "internal_server_error", "details": str(e)}), 500

# ---------- Run ----------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    # Create DB tables if missing
    with app.app_context():
        db.create_all()
    # debug=False for production
    app.run(host="0.0.0.0", port=port, debug=False)
