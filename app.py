# app.py — AiVantu Phase-3 production-ready (SQLite, no psycopg2)
# WARNING: synchronous rendering blocks requests. For production use background workers.

import os
import uuid
import json
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from flask import (
    Flask, request, jsonify, url_for, send_from_directory, abort
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from flask_cors import CORS

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
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
CORS(app)  # allow cross-origin for Flutter frontend
app.config["SECRET_KEY"] = os.getenv("APP_SECRET_KEY", "aivantu-secret")
# Use SQLite by default. When you want Postgres later, set DATABASE_URL env var (and add psycopg2 in requirements).
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", f"sqlite:///{str(BASE_DIR / 'data.db')}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["OUTPUT_FOLDER"] = str(OUTPUT_FOLDER)
app.config["TMP_FOLDER"] = str(TMP_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", 700)) * 1024 * 1024

db = SQLAlchemy(app)

# ---------- Models ----------
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


class Plan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    price = db.Column(db.String(50))
    features = db.Column(db.String(255))


# ---------- DB init with defaults ----------
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

def _abs_path(rel_or_abs: str) -> str:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = BASE_DIR / rel_or_abs
    return str(p.resolve())

# ---------- Rendering helpers (moviepy) ----------
def create_lip_sync_like_clip(image_path: str, duration: float, size_width: int = 1280):
    from moviepy.editor import ImageClip, concatenate_videoclips
    from moviepy.video.fx.all import resize
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
                                  output_rel_path: str, quality: str = "HD",
                                  bg_music_rel: Optional[str] = None):
    from moviepy.editor import AudioFileClip, concatenate_videoclips, CompositeAudioClip
    out_abs = _abs_path(output_rel_path)
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
    if quality and quality.lower() in ("fullhd", "full hd", "1080", "1080p"):
        bitrate = "2500k"
    if quality and quality.lower() in ("4k", "2160", "2160p"):
        bitrate = "8000k"
    final_video.write_videofile(out_abs, fps=24, codec="libx264", audio_codec="aac", bitrate=bitrate)
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
    return jsonify({"msg": "AiVantu Phase3 backend running", "status": "ok"})

# ---------- Template suggestion ----------
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

# ---------- Preview voice (gTTS) ----------
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
        return jsonify({"audio_url": url_for("uploaded_file", filename=str(Path("audio")/dest.name))}), 200
    except Exception as e:
        log.exception("Preview voice error")
        return jsonify({"error": "TTS generation failed", "details": str(e)}), 500

# ---------- Assistant ----------
@app.route("/assistant", methods=["POST"])
def assistant():
    data = request.json or {}
    q = data.get("query","")
    lang = data.get("lang","hi")
    reply = f"AI Suggestion: Improve the opening line and add a short CTA. You asked: {q}"
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
        audio_url = url_for("uploaded_file", filename=str(Path("audio")/dest.name))
    except Exception:
        audio_url = None
    return jsonify({"reply": reply, "audio_url": audio_url}), 200

# ---------- Payment endpoints (placeholders) ----------
# Razorpay: uses RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET env vars
@app.route("/pay/razorpay/create_order", methods=["POST"])
def razorpay_create_order():
    data = request.json or {}
    amount = int(data.get("amount", 0))  # amount in smallest currency unit (e.g., paise)
    receipt = data.get("receipt", f"rcpt_{uuid.uuid4().hex[:8]}")
    # if razorpay library available, create real order; else return placeholder
    try:
        import razorpay
        key_id = os.getenv("RAZORPAY_KEY_ID")
        key_secret = os.getenv("RAZORPAY_KEY_SECRET")
        if not key_id or not key_secret:
            return jsonify({"error":"razorpay credentials not configured"}), 400
        client = razorpay.Client(auth=(key_id, key_secret))
        order = client.order.create({"amount": amount, "currency":"INR", "receipt": receipt})
        return jsonify(order), 200
    except Exception as e:
        log.exception("Razorpay create_order failed")
        return jsonify({"order_id": f"test_{uuid.uuid4().hex}", "amount": amount, "currency":"INR", "note":"razorpay not installed/credentials missing", "error": str(e)}), 200

# PayPal placeholder (for real use integrate PayPal SDK and client id/secret env)
@app.route("/pay/paypal/create_payment", methods=["POST"])
def paypal_create_payment():
    data = request.json or {}
    amount = data.get("amount", "0.00")
    return jsonify({"id": f"paypal_test_{uuid.uuid4().hex}", "amount": amount, "note":"paypal flow placeholder - integrate SDK for production"}), 200

# ---------- Main: generate multi-character video ----------
@app.route("/generate_video", methods=["POST"])
def generate_video():
    demo_user_email = request.form.get("user_email", "demo@aivantu.com")
    title = request.form.get("title") or f"Video {datetime.utcnow().isoformat()}"
    script = request.form.get("script", "") or ""
    template = request.form.get("template", "Default")
    quality = request.form.get("quality", "HD")
    length_type = request.form.get("length_type", "short")
    lang = request.form.get("lang", "hi")
    bg_music_choice = request.form.get("bg_music", "")

    video = UserVideo(user_email=demo_user_email, title=title, script=script,
                      template=template, quality=quality, length_type=length_type,
                      background_music=bg_music_choice, status="rendering")
    db.session.add(video)
    db.session.commit()

    job_id = f"video_{video.id}"
    log.info("Render job start: %s", job_id)

    # Save images
    image_rel_paths = []
    if "characters" in request.files:
        files = request.files.getlist("characters")
        for f in files:
            if f and allowed_file(f.filename, ALLOWED_IMAGE_EXT):
                saved = save_upload(f, "characters")
                image_rel_paths.append(saved)

    # fallback placeholder if no images
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
                log.exception("Placeholder creation failed")
                video.status = "failed"
                db.session.commit()
                return jsonify({"status":"error","message":"No characters and placeholder creation failed","details":str(e)}), 400

    # bg music file
    bg_music_rel = None
    bg_music_file = request.files.get("bg_music_file")
    if bg_music_file and allowed_file(bg_music_file.filename, ALLOWED_AUDIO_EXT):
        bg_music_rel = save_upload(bg_music_file, "music")
    else:
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

    # voice type list (if no upload) — pad for number of characters
    voice_types = request.form.getlist("voice_type")
    if len(voice_types) < len(image_rel_paths):
        default = voice_types[0] if voice_types else "Female"
        while len(voice_types) < len(image_rel_paths):
            voice_types.append(default)

    # split script for characters
    char_texts = []
    markers = [f"[C{i+1}]:" for i in range(len(image_rel_paths))]
    if any(m in script for m in markers):
        remaining = script
        for i, m in enumerate(markers):
            idx = remaining.find(m)
            if idx == -1:
                char_texts.append("")
                continue
            next_pos = min([remaining.find(x, idx+1) for x in markers if remaining.find(x, idx+1) != -1] + [len(remaining)])
            part = remaining[idx+len(m):next_pos].strip()
            char_texts.append(part)
    else:
        sentences = [s.strip() for s in script.replace("\r","\n").split("\n") if s.strip()]
        if not sentences:
            words = script.split()
            if not words:
                char_texts = ["Hello from AiVantu"] + [""]*(len(image_rel_paths)-1)
            else:
                per = max(1, len(words)//len(image_rel_paths))
                for i in range(len(image_rel_paths)):
                    part_words = words[i*per:(i+1)*per] if i < len(image_rel_paths)-1 else words[i*per:]
                    char_texts.append(" ".join(part_words).strip())
        else:
            char_texts = [""] * len(image_rel_paths)
            for idx, s in enumerate(sentences):
                char_texts[idx % len(image_rel_paths)] += (s + " ")
            char_texts = [c.strip() for c in char_texts]

    while len(char_texts) < len(image_rel_paths):
        char_texts.append("")

    # Build audio files per character: prefer custom uploaded voice -> else gTTS
    audio_rel_paths = []
    for i in range(len(image_rel_paths)):
        if i < len(char_voice_files):
            audio_rel_paths.append(char_voice_files[i])
            continue
        text_for_char = char_texts[i] if i < len(char_texts) else ""
        if not text_for_char.strip():
            # create a short empty TTS (space) to ensure an audio file exists
            try:
                from gtts import gTTS
                uid = uuid.uuid4().hex
                out = Path(app.config["TMP_FOLDER"]) / f"{job_id}_empty_{i}_{uid}.mp3"
                tts = gTTS(" ", lang=lang)
                tts.save(str(out))
                dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(out), str(dest))
                audio_rel_paths.append(str(Path("audio") / dest.name))
            except Exception:
                p = Path(app.config["TMP_FOLDER"]) / f"{job_id}_silent_{i}.mp3"
                p.write_bytes(b"")
                audio_rel_paths.append(str(p.relative_to(BASE_DIR)))
            continue
        try:
            from gtts import gTTS
            uid = uuid.uuid4().hex
            out = Path(app.config["TMP_FOLDER"]) / f"{job_id}_{i}_{uid}.mp3"
            tts = gTTS(text_for_char, lang=lang)
            tts.save(str(out))
            dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(out), str(dest))
            audio_rel_paths.append(str(Path("audio") / dest.name))
        except Exception as e:
            log.exception("TTS generation failed for char %s: %s", i, e)
            video.status = "failed"
            db.session.commit()
            return jsonify({"status":"error","message":"TTS generation failed","details":str(e)}), 500

    # Compose output filename
    out_name = f"video_{video.id}.mp4"
    out_abs = Path(app.config["OUTPUT_FOLDER"]) / out_name

    try:
        render_video_multi_characters(image_rel_paths, audio_rel_paths, str(out_abs), quality=quality, bg_music_rel=bg_music_rel)
        video.file_path = str(Path("outputs") / out_name)
        video.status = "done"
        video.meta_json = json.dumps({
            "script": script,
            "characters": image_rel_paths,
            "voices": [*voice_types],
            "quality": quality,
            "created_at": datetime.utcnow().isoformat()
        })
        db.session.commit()
    except Exception as e:
        log.exception("Render failed: %s", e)
        video.status = "failed"
        db.session.commit()
        return jsonify({"status":"error","message":"Render failed","details":str(e)}), 500

    download_url = url_for("output_file", filename=out_name, _external=True)
    return jsonify({"status":"done","video_id":video.id,"download_url":download_url}), 200

# ---------- Run ----------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
