# app.py — AiVantu Phase-3 (production-ready single-file)
# - SQLite-only (protects from psycopg2 errors on free render)
# - Multi-character + TTS (gTTS) + moviepy renderer (synchronous)
# - Profile, gallery, admin, dashboard, assistant, preview_voice, generate_video
# - Payment placeholders included (razorpay / paypal integration points)
#
# Requirements (example):
# flask==3.0.3
# flask_sqlalchemy==3.1.1
# gtts==2.5.1
# moviepy==1.0.3
# pillow==10.4.0
# opencv-python-headless==4.10.0.84  # optional for advanced editing
# pydub==0.25.1                      # optional audio utils
# razorpay==1.4.2                    # placeholder (only used in admin / config)
# paypalrestsdk==1.13.1              # placeholder
# gunicorn==23.0.0
# python-dotenv==1.0.1
# Note: do NOT add psycopg2 to requirements if deploying on a free Render plan.

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

# ---------------- logging ----------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aivantu")

# ---------------- directories ----------------
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
OUTPUT_FOLDER = BASE_DIR / "outputs"
TMP_FOLDER = BASE_DIR / "tmp"
for p in (UPLOAD_FOLDER, OUTPUT_FOLDER, TMP_FOLDER):
    p.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_AUDIO_EXT = {"mp3", "wav", "ogg", "m4a"}
ALLOWED_VIDEO_EXT = {"mp4", "mov", "mkv", "webm"}

# ---------------- flask + db ----------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("APP_SECRET_KEY", "aivantu-secret")

# Force SQLite if DATABASE_URL refers to postgres or is not set.
env_db = os.getenv("DATABASE_URL", "").strip()
if env_db and ("postgres" in env_db or "psycopg" in env_db.lower()):
    log.warning("Detected PostgreSQL DATABASE_URL in env — overriding to SQLite for free deploy compatibility.")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{str(BASE_DIR/'data.db')}"
else:
    # Use DATABASE_URL if provided and doesn't mention postgres; otherwise fallback to sqlite
    app.config["SQLALCHEMY_DATABASE_URI"] = env_db or f"sqlite:///{str(BASE_DIR/'data.db')}"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["OUTPUT_FOLDER"] = str(OUTPUT_FOLDER)
app.config["TMP_FOLDER"] = str(TMP_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", 700)) * 1024 * 1024

db = SQLAlchemy(app)

# ---------------- models ----------------
class UserVideo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(255), nullable=False)
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
    photo_path = db.Column(db.String(1024))
    voice_path = db.Column(db.String(1024))
    ai_style = db.Column(db.String(50))
    mood = db.Column(db.String(50))
    is_locked = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CharacterBundle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), default="Bundle")
    characters_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Plan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    price = db.Column(db.String(50))
    features = db.Column(db.String(255))

# ---------------- DB init defaults ----------------
with app.app_context():
    db.create_all()
    if not VoiceOption.query.first():
        db.session.add_all([
            VoiceOption(display_name="Female", description="Soft female voice"),
            VoiceOption(display_name="Male", description="Deep male voice"),
            VoiceOption(display_name="Child", description="Child voice"),
            VoiceOption(display_name="Celebrity", description="Celebrity-like demo"),
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

# ---------------- helpers ----------------
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

def _abs_path(rel_or_abs: str) -> str:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = BASE_DIR / rel_or_abs
    return str(p.resolve())

def save_temp_bytes(name: str, data: bytes) -> str:
    dest = Path(app.config["TMP_FOLDER"]) / name
    dest.write_bytes(data)
    return str(dest)

# ---------------- rendering helpers (moviepy) ----------------
def create_lip_sync_like_clip(image_path: str, duration: float, size_width: int = 1280):
    try:
        from moviepy.editor import ImageClip, concatenate_videoclips
        from moviepy.video.fx.all import resize
    except Exception as e:
        raise RuntimeError("moviepy is required for rendering. Install moviepy and ffmpeg available in PATH.") from e

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
    try:
        from moviepy.editor import AudioFileClip, concatenate_videoclips, CompositeAudioClip
    except Exception as e:
        raise RuntimeError("moviepy is required for rendering. Install moviepy and ffmpeg available in PATH.") from e

    clips = []
    audios = []
    n = min(len(image_rel_paths), len(audio_rel_paths))
    if n == 0:
        raise ValueError("No character images or audios provided for rendering")

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
            from moviepy.editor import AudioFileClip as _AFC, concatenate_audioclips
            bg_clip = _AFC(bg_abs)
            if bg_clip.duration < final_video.duration:
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
    if quality and quality.lower() in ("fullhd", "full hd", "1080", "1080p"):
        bitrate = "2500k"
    if quality and quality.lower() in ("4k", "2160", "2160p"):
        bitrate = "8000k"

    final_video.write_videofile(str(output_abs_path), fps=24, codec="libx264", audio_codec="aac", bitrate=bitrate)
    final_video.close()
    for a in audios:
        try:
            a.close()
        except:
            pass

# ---------------- simple HTML base (for quick checks) ----------------
BASE_HTML = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AiVantu</title><style>
body{font-family:Inter, Arial;background:#fff;margin:0;padding:20px}
.card{background:#fff;border-radius:10px;padding:18px;max-width:980px;margin:20px auto;box-shadow:0 8px 30px rgba(0,0,0,.08)}
.btn{display:inline-block;padding:8px 12px;border-radius:8px;background:#2563eb;color:#fff;text-decoration:none}
input,textarea,select{width:100%;padding:8px;margin:8px 0;border:1px solid #eee;border-radius:8px}
</style></head><body><div class="card">
<h1>AiVantu</h1>
<div style="display:flex;gap:8px;margin-bottom:12px">
<a class="btn" href="{{ url_for('dashboard') }}">Dashboard</a>
<a class="btn" href="{{ url_for('create_video') }}">Create</a>
<a class="btn" href="{{ url_for('gallery') }}">Gallery</a>
<a class="btn" href="{{ url_for('profile') }}">Profile</a>
<a class="btn" href="{{ url_for('admin_home') }}">Admin</a>
</div>
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}{% for c,m in messages %}<div style="margin:6px 0;color:#111">{{ m }}</div>{% endfor %}{% endif %}
{% endwith %}
{% block body %}{% endblock %}
</div></body></html>
"""

# ---------------- routes ----------------
@app.route("/")
def index():
    return redirect(url_for("dashboard"))

@app.route("/dashboard")
def dashboard():
    demo_user = "demo@aivantu.com"
    videos = UserVideo.query.filter_by(user_email=demo_user).order_by(UserVideo.created_at.desc()).all()
    return render_template_string(BASE_HTML + """
    {% block body %}
    <h3>Dashboard</h3>
    <p>Total videos: {{ videos|length }}</p>
    <table style="width:100%;border-collapse:collapse">
      <tr><th style="text-align:left">Title</th><th>Template</th><th>Quality</th><th>Action</th></tr>
      {% for v in videos %}
      <tr><td>{{ v.title }}</td><td>{{ v.template }}</td><td>{{ v.quality }}</td>
      <td>
        {% if v.file_path %}<a href="{{ url_for('output_file', filename=v.file_path.split('/')[-1]) }}">Download</a>{% else %}—{% endif %}
      </td></tr>
      {% endfor %}
    </table>
    {% endblock %}
    """, videos=videos)

@app.route("/create_video", methods=["GET","POST"])
def create_video():
    demo_user = "demo@aivantu.com"
    if request.method == "POST":
        title = request.form.get("title") or f"Video {datetime.utcnow().isoformat()}"
        script = request.form.get("script","")
        template = request.form.get("template","Default")
        quality = request.form.get("quality","HD")
        length_type = request.form.get("length_type","short")
        lang = request.form.get("lang","hi")
        # Save files & redirect to generate endpoint (form posts to /generate_video)
        # We'll accept characters and voice files here and forward to generate_video for convenience
        files = {}
        for key in ("characters","character_voice_files","bg_music_file","user_voice"):
            if key in request.files:
                files[key] = request.files.getlist(key) if key.endswith("s") else [request.files.get(key)]
        # Instead of internal forwarding, ask client to POST to /generate_video; but provide quick-call form:
        # For ease, create a DB entry/preview and redirect to dashboard.
        v = UserVideo(user_email=demo_user, title=title, script=script, template=template,
                      voices="", quality=quality, length_type=length_type, status="ready")
        db.session.add(v); db.session.commit()
        flash("Saved. Use /generate_video to render actual video (form-data w/ files).", "success")
        return redirect(url_for("dashboard"))

    templates = TemplateCatalog.query.all()
    voices = VoiceOption.query.all()
    return render_template_string(BASE_HTML + """
    {% block body %}
    <h3>Create video (quick)</h3>
    <form method="post" enctype="multipart/form-data">
      <input name="title" placeholder="Title">
      <textarea name="script" rows="6" placeholder="Script"></textarea>
      <select name="template">{% for t in templates %}<option>{{t.name}}</option>{% endfor %}</select>
      <select name="quality"><option>HD</option><option>FULLHD</option><option>4K</option></select>
      <select name="lang"><option value="hi">hi</option><option value="en">en</option><option value="bn">bn</option></select>
      <button class="btn">Save</button>
    </form>
    <p class="note">For full render (with images/audio) POST to <code>/generate_video</code> (form-data)</p>
    {% endblock %}
    """, templates=templates, voices=voices)

@app.route("/gallery")
def gallery():
    demo_user = "demo@aivantu.com"
    videos = UserVideo.query.filter_by(user_email=demo_user).all()
    return render_template_string(BASE_HTML + """
    {% block body %}
    <h3>Gallery</h3>
    {% for v in videos %}
      <div style="margin:8px 0"><strong>{{ v.title }}</strong> — {{ v.status }} —
      {% if v.file_path %}<a href="{{ url_for('output_file', filename=v.file_path.split('/')[-1]) }}">Download</a>{% else %}No file{% endif %}</div>
    {% endfor %}
    {% endblock %}
    """, videos=videos)

@app.route("/profile", methods=["GET","POST"])
def profile():
    demo_user = "demo@aivantu.com"
    profile = UserProfile.query.filter_by(email=demo_user).first()
    if request.method == "POST":
        name = request.form.get("name")
        country = request.form.get("country")
        if profile:
            profile.name = name or profile.name
            profile.country = country or profile.country
        else:
            profile = UserProfile(email=demo_user, name=name, country=country)
            db.session.add(profile)
        db.session.commit()
        flash("Profile updated", "success")
        return redirect(url_for("profile"))
    return render_template_string(BASE_HTML + """
    {% block body %}
    <h3>Profile</h3>
    <form method="post">
      <input name="name" value="{{ profile.name if profile else '' }}" placeholder="Name">
      <input name="country" value="{{ profile.country if profile else '' }}" placeholder="Country">
      <button class="btn">Save</button>
    </form>
    {% endblock %}
    """, profile=profile)

@app.route("/admin")
def admin_home():
    temps = TemplateCatalog.query.all()
    plans = Plan.query.all()
    return render_template_string(BASE_HTML + """
    {% block body %}
    <h3>Admin</h3>
    <h4>Templates</h4>
    {% for t in temps %}<div>{{ t.name }} — {{ t.category }}</div>{% endfor %}
    <h4>Plans</h4>
    {% for p in plans %}<div>{{ p.name }} — {{ p.price }} — {{ p.features }}</div>{% endfor %}
    {% endblock %}
    """, temps=temps, plans=plans)

# ---------------- static file serving ----------------
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/outputs/<path:filename>")
def output_file(filename):
    return send_from_directory(app.config["OUTPUT_FOLDER"], filename)

# ---------------- assistant & TTS preview ----------------
@app.route("/assistant", methods=["POST"])
def assistant():
    data = request.json or {}
    q = data.get("query","")
    lang = data.get("lang","hi")
    reply = f"AI Suggestion: Make the opening line punchy and add a short CTA. You asked: {q}"
    audio_url = None
    try:
        from gtts import gTTS
        uid = uuid.uuid4().hex
        out = Path(app.config["TMP_FOLDER"]) / f"assistant_{uid}.mp3"
        tts = gTTS(reply, lang=lang)
        tts.save(str(out))
        dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out), str(dest))
        audio_url = url_for("uploaded_file", filename=str(Path("audio")/dest.name), _external=True)
    except Exception:
        audio_url = None
    return jsonify({"reply": reply, "audio_url": audio_url})

@app.route("/preview_voice", methods=["POST"])
def preview_voice():
    text = request.form.get("text", "Preview from AiVantu")
    lang = request.form.get("lang", "hi")
    try:
        from gtts import gTTS
        uid = uuid.uuid4().hex
        out = Path(app.config["TMP_FOLDER"]) / f"preview_{uid}.mp3"
        tts = gTTS(text, lang=lang)
        tts.save(str(out))
        dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out), str(dest))
        return jsonify({"audio_url": url_for("uploaded_file", filename=str(Path("audio")/dest.name), _external=True)}), 200
    except Exception as e:
        log.exception("Preview TTS error")
        return jsonify({"error": "TTS generation failed", "details": str(e)}), 500

# ---------------- main generation endpoint ----------------
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
    - lang (e.g., 'hi', 'en')
    - bg_music (preset name) OR bg_music_file (file)
    - characters[] (multiple image files)
    - character_voice_files[] (optional) -> custom voice file per character (order aligned)
    - voice_type[] (optional) -> style per character (placeholder)
    """
    demo_user = request.form.get("user_email", "demo@aivantu.com")
    title = request.form.get("title") or f"Video {datetime.utcnow().isoformat()}"
    script = request.form.get("script","") or ""
    template = request.form.get("template","Default")
    quality = request.form.get("quality","HD")
    length_type = request.form.get("length_type","short")
    lang = request.form.get("lang","hi")
    bg_music_choice = request.form.get("bg_music","")

    # create DB entry
    video = UserVideo(user_email=demo_user, title=title, script=script, template=template,
                      voices="", quality=quality, length_type=length_type,
                      background_music=bg_music_choice, status="rendering")
    db.session.add(video); db.session.commit()
    job_id = f"video_{video.id}"
    log.info("Render job start: %s", job_id)

    # images
    image_rel_paths = []
    if "characters" in request.files:
        files = request.files.getlist("characters")
        for f in files:
            if f and allowed_file(f.filename, ALLOWED_IMAGE_EXT):
                image_rel_paths.append(save_upload(f, "characters"))

    # placeholder if none
    if not image_rel_paths:
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
                log.exception("placeholder failed")
                video.status = "failed"; db.session.commit()
                return jsonify({"status":"error","message":"No images and placeholder failed","details":str(e)}), 400

    # bg music file
    bg_music_rel = None
    bg_music_file = request.files.get("bg_music_file")
    if bg_music_file and allowed_file(bg_music_file.filename, ALLOWED_AUDIO_EXT):
        bg_music_rel = save_upload(bg_music_file, "music")
    else:
        if bg_music_choice:
            p = Path(app.config["UPLOAD_FOLDER"]) / "music" / f"{bg_music_choice}.mp3"
            if p.exists(): bg_music_rel = str(Path("music") / p.name)

    # character voice files (optional)
    char_voice_files = []
    if "character_voice_files" in request.files:
        vfiles = request.files.getlist("character_voice_files")
        for vf in vfiles:
            if vf and allowed_file(vf.filename, ALLOWED_AUDIO_EXT):
                char_voice_files.append(save_upload(vf, "user_voices"))

    # voice types (placeholder)
    voice_types = request.form.getlist("voice_type")
    if len(voice_types) < len(image_rel_paths):
        default = voice_types[0] if voice_types else "Female"
        while len(voice_types) < len(image_rel_paths):
            voice_types.append(default)

    # split script into parts for each character:
    char_texts = []
    markers = [f"[C{i+1}]:" for i in range(len(image_rel_paths))]
    if any(m in script for m in markers):
        remaining = script
        for i,m in enumerate(markers):
            idx = remaining.find(m)
            if idx == -1:
                char_texts.append("")
                continue
            next_pos = min([remaining.find(x, idx+1) for x in markers if remaining.find(x, idx+1) != -1] + [len(remaining)])
            part = remaining[idx+len(m):next_pos].strip()
            char_texts.append(part)
    else:
        # split by newlines or distribute words
        lines = [l.strip() for l in script.splitlines() if l.strip()]
        if lines:
            char_texts = [""]*len(image_rel_paths)
            for idx,l in enumerate(lines):
                char_texts[idx % len(image_rel_paths)] += (l + " ")
            char_texts = [c.strip() for c in char_texts]
        else:
            # fallback: if script blank, give first character a default line
            if script.strip():
                words = script.split()
                per = max(1, len(words)//len(image_rel_paths))
                for i in range(len(image_rel_paths)):
                    part_words = words[i*per:(i+1)*per] if i < len(image_rel_paths)-1 else words[i*per:]
                    char_texts.append(" ".join(part_words).strip())
            else:
                char_texts = ["Hello from AiVantu"] + [""]*(len(image_rel_paths)-1)

    while len(char_texts) < len(image_rel_paths):
        char_texts.append("")

    # Build audio per character: uploaded voice file > gTTS generated
    audio_rel_paths = []
    for i in range(len(image_rel_paths)):
        if i < len(char_voice_files):
            audio_rel_paths.append(char_voice_files[i])
            continue
        txt = char_texts[i] if i < len(char_texts) else ""
        if not txt.strip():
            # create a very short silent TTS or blank audio by using gTTS with a space
            try:
                from gtts import gTTS
                uid = uuid.uuid4().hex
                out = Path(app.config["TMP_FOLDER"]) / f"{job_id}_empty_{i}_{uid}.mp3"
                tts = gTTS(" ", lang=lang)
                tts.save(str(out))
                dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(out), str(dest))
                audio_rel_paths.append(str(Path("audio")/dest.name))
            except Exception:
                # fallback empty file
                p = Path(app.config["TMP_FOLDER"]) / f"{job_id}_silent_{i}.mp3"
                p.write_bytes(b"")
                audio_rel_paths.append(str(p.relative_to(BASE_DIR)))
            continue
        try:
            from gtts import gTTS
            uid = uuid.uuid4().hex
            out = Path(app.config["TMP_FOLDER"]) / f"{job_id}_{i}_{uid}.mp3"
            tts = gTTS(txt, lang=lang)
            tts.save(str(out))
            dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(out), str(dest))
            audio_rel_paths.append(str(Path("audio")/dest.name))
        except Exception as e:
            log.exception("TTS failed for char %s: %s", i, e)
            video.status = "failed"; db.session.commit()
            return jsonify({"status":"error","message":"TTS generation failed","details":str(e)}), 500

    # Compose and render (synchronously)
    out_name = f"video_{video.id}.mp4"
    out_abs = Path(app.config["OUTPUT_FOLDER"]) / out_name
    try:
        render_video_multi_characters(image_rel_paths, audio_rel_paths, out_abs, quality=quality, bg_music_rel=bg_music_rel)
        video.file_path = str(Path("outputs") / out_name)
        video.status = "done"
        video.meta_json = json.dumps({
            "script": script,
            "characters": image_rel_paths,
            "voices": voice_types,
            "bg_music": bg_music_rel,
            "created_at": datetime.utcnow().isoformat()
        })
        db.session.commit()
    except Exception as e:
        log.exception("Render failed: %s", e)
        video.status = "failed"; db.session.commit()
        return jsonify({"status":"error","message":"Render failed","details":str(e)}), 500

    download_url = url_for("output_file", filename=out_name, _external=True)
    return jsonify({"status":"done","video_id":video.id,"download_url":download_url}), 200

# ---------------- run ----------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
