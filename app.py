# app.py — AiVantu Phase-3 final (single-file)
# Features:
# - Multi-character, multi-voice (user-uploaded voice priority; else gTTS per-character)
# - Multi-language (user selects `lang`)
# - Naive lip-sync simulation (subtle image transform alternation)
# - MoviePy renderer: stitches per-character clips + audio + optional bg music
# - DB: stores videos, profiles, templates, voices, characters
# - Endpoints: /generate_video (form-data), /preview_voice, /assistant, /gallery, /dashboard, /profile, /admin
#
# Requirements (install on server):
# pip install flask flask_sqlalchemy gtts moviepy pillow sqlalchemy werkzeug
# ffmpeg must be installed on the machine and accessible in PATH for moviepy to work.
#
# WARNING: Synchronous rendering in /generate_video blocks the request — in production push rendering to a queue (Celery/RQ).
# For small test jobs it's fine, but for larger loads use background workers.

import os
import uuid
import json
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from flask import (
    Flask, render_template_string, request, redirect, url_for, flash,
    send_from_directory, jsonify, abort
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

# logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aivantu")

# ---------- Config ----------
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
OUTPUT_FOLDER = BASE_DIR / "outputs"
TMP_FOLDER = BASE_DIR / "tmp"
for p in (UPLOAD_FOLDER, OUTPUT_FOLDER, TMP_FOLDER):
    p.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_AUDIO_EXT = {"mp3", "wav", "ogg", "m4a"}
ALLOWED_VIDEO_EXT = {"mp4", "mov", "mkv", "webm"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("APP_SECRET_KEY", "aivantu-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", f"sqlite:///{str(BASE_DIR / 'data.db')}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["OUTPUT_FOLDER"] = str(OUTPUT_FOLDER)
app.config["TMP_FOLDER"] = str(TMP_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", 700)) * 1024 * 1024  # default 700MB

db = SQLAlchemy(app)

# ---------- Models ----------
class UserVideo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(255))
    script = db.Column(db.Text)
    template = db.Column(db.String(255))
    voices = db.Column(db.String(255))          # comma-separated voice descriptors
    quality = db.Column(db.String(20))
    length_type = db.Column(db.String(20))      # short/long
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


class UserProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True)
    name = db.Column(db.String(100))
    country = db.Column(db.String(100))
    photo = db.Column(db.String(255))
    plan = db.Column(db.String(50), default="Free")


class UserCharacter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), default="My Character")
    photo_path = db.Column(db.String(1024))      # uploaded photo OR AI generated
    voice_path = db.Column(db.String(1024))      # uploaded custom voice
    ai_style = db.Column(db.String(50))          # cartoon / anime / 3d
    mood = db.Column(db.String(50))
    is_locked = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CharacterBundle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), default="Bundle")
    characters_json = db.Column(db.Text)         # list of UserCharacter ids
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Plan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    price = db.Column(db.String(50))
    features = db.Column(db.String(255))


# ---------- DB init defaults ----------
with app.app_context():
    db.create_all()
    if not VoiceOption.query.first():
        db.session.add_all([
            VoiceOption(display_name="Female", description="Soft female voice"),
            VoiceOption(display_name="Male", description="Deep male voice"),
            VoiceOption(display_name="Child", description="Child voice"),
            VoiceOption(display_name="Celebrity", description="Celebrity-like demo")
        ])
    if not TemplateCatalog.query.first():
        db.session.add_all([
            TemplateCatalog(name="Motivation", category="Inspiration"),
            TemplateCatalog(name="Promo", category="Marketing"),
            TemplateCatalog(name="Explainer", category="Education"),
            TemplateCatalog(name="Kids", category="Cartoon"),
            TemplateCatalog(name="Event", category="Celebration"),
        ])
    if not Plan.query.first():
        db.session.add_all([
            Plan(name="Free", price="0", features="Low quality, 1 render/day"),
            Plan(name="Premium", price="499", features="FullHD, 10 renders/day"),
            Plan(name="Pro", price="999", features="4K, unlimited renders"),
        ])
    if not UserProfile.query.filter_by(email="demo@aivantu.com").first():
        db.session.add(UserProfile(email="demo@aivantu.com", name="Demo User", country="India"))
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
    log.info(f"Saved upload: {rel}")
    return rel

def save_temp_bytes(name: str, data: bytes) -> str:
    dest = Path(app.config["TMP_FOLDER"]) / name
    dest.write_bytes(data)
    return str(dest)

def cleanup_temp(prefix: Optional[str] = None):
    t = Path(app.config["TMP_FOLDER"])
    for f in t.iterdir():
        try:
            if prefix is None or f.name.startswith(prefix):
                f.unlink()
        except Exception:
            pass

# ---------- Rendering helpers (moviepy) ----------
def _abs_path(rel_or_abs: str) -> str:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = BASE_DIR / rel_or_abs
    return str(p.resolve())

def create_lip_sync_like_clip(image_path: str, duration: float, size_width: int = 1280):
    """
    Create a clip from image with naive 'mouth movement' by alternating subtle transforms.
    This is not real lip-sync; it's a lightweight visual illusion for talking.
    """
    from moviepy.editor import ImageClip, concatenate_videoclips
    from moviepy.video.fx.all import resize, crop

    abs_img = _abs_path(image_path)
    # base clip
    base = ImageClip(abs_img).set_duration(duration).resize(width=size_width)
    # create a slightly zoomed version (simulate small mouth/jaw motion)
    small_movement = base.fx(resize, 0.98)
    # alternate frames every 0.12 seconds to simulate movement while audio plays
    segment = 0.12
    clips = []
    t = 0.0
    toggle = False
    while t < duration - 1e-6:
        seg_d = min(segment, duration - t)
        clip = small_movement.set_duration(seg_d) if toggle else base.set_duration(seg_d)
        clips.append(clip)
        toggle = not toggle
        t += seg_d
    return concatenate_videoclips(clips, method="compose")

def render_video_multi_characters(image_rel_paths: List[str], audio_rel_paths: List[str],
                                  output_rel_path: str, quality: str = "HD",
                                  bg_music_rel: Optional[str] = None):
    """
    Compose a sequence where each character clip speaks its audio.
    image_rel_paths and audio_rel_paths should align (1-to-1). If multiple characters and
    script is conversational, caller may split script & pass arrays in order.
    Output saved under OUTPUT_FOLDER / output_rel_path
    """
    from moviepy.editor import AudioFileClip, concatenate_videoclips, CompositeAudioClip
    out_abs = _abs_path(output_rel_path)
    clips = []
    audios = []

    # For safety: if counts mismatch, use min length
    n = min(len(image_rel_paths), len(audio_rel_paths))
    if n == 0:
        raise ValueError("No character images or audios provided for rendering")

    # create per-character talking clips
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

    # concatenate clips in sequence (this makes conversation)
    final_video = concatenate_videoclips(clips, method="compose")

    # mix background music if provided
    if bg_music_rel:
        try:
            bg_abs = _abs_path(bg_music_rel)
            bg_clip = AudioFileClip(bg_abs)
            # repeat/loop bg to match duration
            if bg_clip.duration < final_video.duration:
                # loop by concatenating copies
                from moviepy.editor import concatenate_audioclips
                n_loops = int(final_video.duration / bg_clip.duration) + 1
                bg_parts = [bg_clip] * n_loops
                bg_clip = concatenate_audioclips(bg_parts).subclip(0, final_video.duration)
            else:
                bg_clip = bg_clip.subclip(0, final_video.duration)
            # lower bg volume
            bg_clip = bg_clip.volumex(0.12)
            # composite main audio (final_video.audio) + bg
            final_audio = CompositeAudioClip([final_video.audio, bg_clip])
            final_video = final_video.set_audio(final_audio)
        except Exception as e:
            log.exception("Failed to load bg music: %s", e)

    # set bitrate based on quality
    bitrate = "800k"
    if quality and quality.lower() in ("fullhd", "full hd", "1080", "1080p"):
        bitrate = "2500k"
    if quality and quality.lower() in ("4k", "2160", "2160p"):
        bitrate = "8000k"

    final_video.write_videofile(out_abs, fps=24, codec="libx264", audio_codec="aac", bitrate=bitrate)
    # cleanup
    final_video.close()
    for a in audios:
        try: a.close()
        except: pass

# ---------- Routes: static & home ----------
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/outputs/<path:filename>")
def output_file(filename):
    return send_from_directory(app.config["OUTPUT_FOLDER"], filename)

@app.route("/")
def home():
    return jsonify({"status": "ok", "message": "AiVantu Phase3 backend running"})

# ---------- API: suggest template ----------
@app.route("/api/suggest_template", methods=["POST"])
def api_suggest_template():
    data = request.json or {}
    script = (data.get("script") or "").lower()
    if not script.strip():
        return jsonify({"suggestion": "Default", "reason": "Script empty"}), 200
    if any(k in script for k in ["promo", "launch", "buy", "sale", "discount"]):
        return jsonify({"suggestion": "Promo", "reason": "Marketing keywords"}), 200
    if any(k in script for k in ["thank you", "congrats", "celebrate", "birthday"]):
        return jsonify({"suggestion": "Event", "reason": "Event keywords found"}), 200
    if any(k in script for k in ["how to", "tutorial", "explain", "guide"]):
        return jsonify({"suggestion": "Explainer", "reason": "Tutorial/explain keywords"}), 200
    if len(script.split()) < 20:
        return jsonify({"suggestion": "Short-Clip", "reason": "Short script"}), 200
    return jsonify({"suggestion": "Narration", "reason": "Long-form content detected"}), 200

# ---------- API: preview voice (gTTS) ----------
@app.route("/preview_voice", methods=["POST"])
def preview_voice():
    text = request.form.get("text", "Preview from AiVantu")
    lang = request.form.get("lang", "hi")  # default Hindi
    tts_voice = request.form.get("voice_type", "Female")  # placeholder for future voice-style selection
    try:
        from gtts import gTTS
        uid = uuid.uuid4().hex
        out = Path(app.config["TMP_FOLDER"]) / f"preview_{uid}.mp3"
        tts = gTTS(text, lang=lang)
        tts.save(str(out))
        dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out), str(dest))
        return jsonify({"audio_url": url_for("uploaded_file", filename=str(Path("audio")/dest.name))}), 200
    except Exception as e:
        log.exception("Preview voice error")
        return jsonify({"error": "TTS generation failed", "details": str(e)}), 500

# ---------- Assistant endpoint (simple) ----------
@app.route("/assistant", methods=["POST"])
def assistant():
    data = request.json or {}
    q = data.get("query","")
    lang = data.get("lang","hi")
    # Basic help: short rewrite + tone suggestion
    reply = f"Short suggestion: Make the opening sentence punchy and add a call-to-action. You asked: {q}"
    # (optionally generate TTS for assistant reply and return audio_url)
    try:
        from gtts import gTTS
        uid = uuid.uuid4().hex
        out = Path(app.config["TMP_FOLDER"]) / f"assistant_{uid}.mp3"
        tts = gTTS(reply, lang=lang)
        tts.save(str(out))
        dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out), str(dest))
        audio_url = url_for("uploaded_file", filename=str(Path("audio")/dest.name))
    except Exception:
        audio_url = None
    return jsonify({"reply": reply, "audio_url": audio_url}), 200

# ---------- Main endpoint: generate multi-character video ----------
@app.route("/generate_video", methods=["POST"])
def generate_video():
    """
    Form-data:
    - user_email (optional)
    - title
    - script
    - template
    - quality
    - length_type
    - lang (e.g., 'hi', 'en', 'bn', 'ta', etc.)
    - bg_music (preset name) OR bg_music_file (file)
    - characters[] (multiple image files)
    - character_voice_files[] (optional) -> custom voice file per character (order aligned)
    - voice_type[] (optional) -> selected style per character (Male/Female/Child/Celebrity) used when no file
    """
    demo_user_email = request.form.get("user_email", "demo@aivantu.com")
    title = request.form.get("title") or f"Video {datetime.utcnow().isoformat()}"
    script = request.form.get("script", "") or ""
    template = request.form.get("template", "Default")
    quality = request.form.get("quality", "HD")
    length_type = request.form.get("length_type", "short")
    lang = request.form.get("lang", "hi")
    bg_music_choice = request.form.get("bg_music", "")

    # early DB entry
    video = UserVideo(user_email=demo_user_email, title=title, script=script,
                      template=template, quality=quality, length_type=length_type,
                      background_music=bg_music_choice, status="rendering")
    db.session.add(video)
    db.session.commit()

    job_id = f"video_{video.id}"
    log.info("Render job start: %s", job_id)

    # save uploaded characters
    image_rel_paths = []
    if "characters" in request.files:
        files = request.files.getlist("characters")
        for f in files:
            if f and allowed_file(f.filename, ALLOWED_IMAGE_EXT):
                saved = save_upload(f, "characters")
                image_rel_paths.append(saved)

    # if no images uploaded, try to use template thumbnail or create placeholder
    if not image_rel_paths:
        tc = TemplateCatalog.query.filter_by(name=template).first()
        if tc and tc.thumbnail:
            image_rel_paths = [tc.thumbnail]
        else:
            # create placeholder PNG
            try:
                from PIL import Image
                placeholder = Path(app.config["TMP_FOLDER"]) / f"{job_id}_ph.png"
                img = Image.new("RGB", (1280,720), color=(250,250,250))
                img.save(placeholder)
                image_rel_paths = [str(placeholder.relative_to(BASE_DIR))]
            except Exception:
                return jsonify({"status":"error","message":"No characters uploaded and placeholder creation failed"}), 400

    # background music uploaded file?
    bg_music_rel = None
    bg_music_file = request.files.get("bg_music_file")
    if bg_music_file and allowed_file(bg_music_file.filename, ALLOWED_AUDIO_EXT):
        bg_music_rel = save_upload(bg_music_file, "music")
    else:
        # try preset mapping (uploads/music/<name>.mp3)
        if bg_music_choice:
            p = Path(app.config["UPLOAD_FOLDER"]) / "music" / f"{bg_music_choice}.mp3"
            if p.exists():
                bg_music_rel = str(Path("music") / p.name)

    # character custom voice files (optional)
    char_voice_files = []
    if "character_voice_files" in request.files:
        vfiles = request.files.getlist("character_voice_files")
        for vf in vfiles:
            if vf and allowed_file(vf.filename, ALLOWED_AUDIO_EXT):
                char_voice_files.append(save_upload(vf, "user_voices"))

    # voice_type selection per character (used when no custom voice)
    voice_types = request.form.getlist("voice_type")  # array aligned with characters; fallback to 'Female'

    # If multiple characters but only one voice_type provided, broadcast it
    if len(voice_types) < len(image_rel_paths):
        # pad with first or default
        default = voice_types[0] if voice_types else "Female"
        while len(voice_types) < len(image_rel_paths):
            voice_types.append(default)

    # Decide audio per character: if custom voice file provided for that index → use it;
    # else use gTTS for that character's assigned script part.
    # For simplicity: if script contains markers like [C1:] [C2:] we split; else split script evenly.
    # Try to split script by markers:
    char_texts = []
    # detect markers [C1:], [C2:], ... up to number of characters
    markers = []
    for i in range(len(image_rel_paths)):
        markers.append(f"[C{i+1}]:")
    # If any marker in script, split by markers:
    if any(m in script for m in markers):
        # crude parse: find each marker and following text until next marker
        remaining = script
        for i, m in enumerate(markers):
            idx = remaining.find(m)
            if idx != -1:
                # take substring from idx+m to next marker in remaining
                nxt_idx = min([remaining.find(x, idx+1) for x in markers if remaining.find(x, idx+1) != -1] + [len(remaining)])
                part = remaining[idx+len(m):nxt_idx].strip()
                char_texts.append(part if part else " ")
            else:
                char_texts.append(" ")
    else:
        # fallback: split script into N roughly equal parts by sentences
        import re
        sentences = re.split(r'(?<=[.!?])\s+', script.strip())
        if not sentences:
            sentences = [script.strip()]
        # distribute sentences round-robin to characters to mimic conversation
        parts = [""] * len(image_rel_paths)
        for idx, s in enumerate(sentences):
            parts[idx % len(parts)] += (s + " ")
        char_texts = [p.strip() if p.strip() else " " for p in parts]

    # Generate or use audio files per character
    audio_rel_paths = []
    from gtts import gTTS
    for i in range(len(image_rel_paths)):
        # priority: char_voice_files provided and index exists
        if i < len(char_voice_files):
            audio_rel_paths.append(char_voice_files[i])
            continue
        # else try to see if user uploaded generic 'user_voice' for all characters?
        # (support single uploaded user_voice param)
        if "user_voice" in request.files:
            uv = request.files.get("user_voice")
            if uv and allowed_file(uv.filename, ALLOWED_AUDIO_EXT):
                uvsaved = save_upload(uv, "user_voices")
                audio_rel_paths.append(uvsaved)
                continue
        # otherwise generate TTS for this character
        text_for_char = char_texts[i] if i < len(char_texts) else " "
        try:
            uid = uuid.uuid4().hex
            tmp = Path(app.config["TMP_FOLDER"]) / f"{job_id}_char{i}_{uid}.mp3"
            # voice_type could be used for future advanced voices; for now we just pass lang
            tts = gTTS(text_for_char or " ", lang=lang)
            tts.save(str(tmp))
            dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / tmp.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp), str(dest))
            audio_rel_paths.append(str(Path("audio")/dest.name))
        except Exception as e:
            log.exception("TTS failed for char %d: %s", i, e)
            video.status = "failed"
            db.session.commit()
            return jsonify({"status":"error","message":"TTS failed","details":str(e)}), 500

    # Now render: outputs/video_<id>.mp4
    out_name = f"video_{video.id}.mp4"
    out_rel = str(Path("outputs")/out_name)
    out_abs = Path(app.config["OUTPUT_FOLDER"]) / out_name

    try:
        # call render function (synchronous)
        render_video_multi_characters(image_rel_paths, audio_rel_paths, out_abs, quality=quality, bg_music_rel=bg_music_rel)
        video.file_path = out_rel
        video.status = "done"
        video.meta_json = json.dumps({
            "image_rel_paths": image_rel_paths,
            "audio_rel_paths": audio_rel_paths,
            "voice_types": voice_types,
            "template": template,
            "quality": quality,
            "lang": lang,
            "created_at": datetime.utcnow().isoformat()
        })
        db.session.commit()
    except Exception as e:
        log.exception("Rendering failed: %s", e)
        video.status = "failed"
        db.session.commit()
        return jsonify({"status":"error","message":"Render failed","details":str(e)}), 500

    # success
    download_url = url_for("output_file", filename=out_name)
    return jsonify({"status":"done", "video_id": video.id, "download_url": download_url}), 200

# ---------- Gallery / Dashboard / Profile / Admin endpoints (simple HTML for demo) ----------
BASE_HTML = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AiVantu Demo</title>
<style>
body{font-family:Inter,Arial;background:#fff;margin:0;padding:18px;color:#222}
.card{max-width:980px;margin:20px auto;padding:18px;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.06);background:#fff}
.btn{display:inline-block;padding:8px 12px;border-radius:8px;background:#2563eb;color:#fff;text-decoration:none}
input,select,textarea{width:100%;padding:8px;margin:6px 0;border:1px solid #eee;border-radius:8px}
small{color:#666}
</style></head><body><div class="card">
<h1>AiVantu (Demo)</h1>
<nav><a class="btn" href="/dashboard">Dashboard</a> <a class="btn" href="/create_demo">Create</a> <a class="btn" href="/gallery">Gallery</a> <a class="btn" href="/profile">Profile</a> <a class="btn" href="/admin">Admin</a></nav>
<hr>
{% block body %}{% endblock %}
</div></body></html>
"""

@app.route("/dashboard")
def dashboard_page():
    demo = "demo@aivantu.com"
    videos = UserVideo.query.filter_by(user_email=demo).order_by(UserVideo.created_at.desc()).all()
    return render_template_string(BASE_HTML + """
    {% block body %}
      <h3>Dashboard</h3>
      <p>Total videos: {{ videos|length }}</p>
      <table border=0 cellpadding=6>
        <tr><th>Title</th><th>Created</th><th>Status</th><th>Download</th></tr>
        {% for v in videos %}
        <tr>
          <td>{{ v.title }}</td>
          <td>{{ v.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
          <td>{{ v.status }}</td>
          <td>{% if v.file_path %}<a href="{{ url_for('output_file', filename=v.file_path.split('/')[-1]) }}">Download</a>{% else %}-{% endif %}</td>
        </tr>
        {% endfor %}
      </table>
    {% endblock %}
    """, videos=videos)

@app.route("/create_demo")
def create_demo_form():
    templates = TemplateCatalog.query.all()
    voices = VoiceOption.query.all()
    return render_template_string(BASE_HTML + """
    {% block body %}
      <h3>Create Demo Video (use /generate_video endpoint for API)</h3>
      <form method="post" action="/generate_video" enctype="multipart/form-data">
        <label>Title</label><input name="title" placeholder="Demo title">
        <label>Language (gTTS lang code)</label><input name="lang" value="hi">
        <label>Script (use [C1]: [C2]: markers to assign character lines)</label>
        <textarea name="script" rows="6">[C1]: Hello! How are you? [C2]: I'm good. Let's make a demo.</textarea>
        <label>Upload character images (order matters)</label><input type="file" name="characters" multiple accept="image/*">
        <label>Upload character voice files (optional, order aligned)</label><input type="file" name="character_voice_files" multiple accept="audio/*">
        <label>BG Music (optional)</label><input type="file" name="bg_music_file" accept="audio/*">
        <label>Quality</label><select name="quality"><option>HD</option><option>FULLHD</option><option>4K</option></select>
        <br><br><button class="btn">Generate (may take time)</button>
      </form>
      <p><small>Note: API /generate_video expects form-data. This form is a convenience demo.</small></p>
    {% endblock %}
    """, templates=templates, voices=voices)

@app.route("/gallery")
def gallery_page():
    demo = "demo@aivantu.com"
    videos = UserVideo.query.filter_by(user_email=demo).order_by(UserVideo.created_at.desc()).all()
    return render_template_string(BASE_HTML + """
    {% block body %}
      <h3>Gallery</h3>
      {% for v in videos %}
        <div style="padding:8px;border-bottom:1px solid #eee;">
          <strong>{{ v.title }}</strong> — {{ v.created_at.strftime('%Y-%m-%d %H:%M') }} — {{ v.status }}
          {% if v.file_path %} — <a href="{{ url_for('output_file', filename=v.file_path.split('/')[-1]) }}">Download</a>{% endif %}
        </div>
      {% endfor %}
    {% endblock %}
    """, videos=videos)

@app.route("/profile", methods=["GET","POST"])
def profile_page():
    demo = "demo@aivantu.com"
    profile = UserProfile.query.filter_by(email=demo).first()
    if request.method == "POST":
        profile.name = request.form.get("name") or profile.name
        profile.country = request.form.get("country") or profile.country
        img = request.files.get("photo")
        if img and allowed_file(img.filename, ALLOWED_IMAGE_EXT):
            profile.photo = save_upload(img, "profile")
        db.session.commit()
        flash("Profile saved")
        return redirect(url_for("profile_page"))
    return render_template_string(BASE_HTML + """
    {% block body %}
      <h3>Profile</h3>
      <form method="post" enctype="multipart/form-data">
        <input name="name" value="{{ profile.name }}">
        <input name="country" value="{{ profile.country }}">
        <input type="file" name="photo" accept="image/*">
        <button class="btn">Save</button>
      </form>
    {% endblock %}
    """, profile=profile)

@app.route("/admin")
def admin_page():
    temps = TemplateCatalog.query.all()
    voices = VoiceOption.query.all()
    plans = Plan.query.all()
    return render_template_string(BASE_HTML + """
    {% block body %}
      <h3>Admin</h3>
      <p>Templates:</p><ul>{% for t in temps %}<li>{{ t.name }} ({{ t.category }})</li>{% endfor %}</ul>
      <p>Voices:</p><ul>{% for v in voices %}<li>{{ v.display_name }}</li>{% endfor %}</ul>
      <p>Plans:</p><ul>{% for p in plans %}<li>{{ p.name }} - {{ p.price }}</li>{% endfor %}</ul>
    {% endblock %}
    """, temps=temps, voices=voices, plans=plans)

# ---------- Error handler ----------
@app.errorhandler(413)
def large(e):
    return jsonify({"error":"file too large","max_mb":int(app.config["MAX_CONTENT_LENGTH"]/1024/1024)}), 413

# ---------- Run ----------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    # DEBUG: set to False in production
    app.run(host="0.0.0.0", port=port, debug=False)
