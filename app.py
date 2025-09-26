# app.py — AiVantu Phase-3 final (production-ready API single-file)
# Requirements: flask, flask_sqlalchemy, gtts, moviepy, pillow, requests, python-dotenv
# ffmpeg must be installed on server (moviepy backend)

import os, uuid, json, shutil, logging, requests
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from flask import Flask, request, jsonify, url_for, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

# logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aivantu")

# Paths
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
OUTPUT_FOLDER = BASE_DIR / "outputs"
TMP_FOLDER = BASE_DIR / "tmp"
for p in (UPLOAD_FOLDER, OUTPUT_FOLDER, TMP_FOLDER):
    p.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_AUDIO_EXT = {"mp3", "wav", "ogg", "m4a"}
ALLOWED_VIDEO_EXT = {"mp4", "mov", "mkv", "webm"}

# Flask app
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("APP_SECRET_KEY", "aivantu-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", f"sqlite:///{str(BASE_DIR/'data.db')}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["OUTPUT_FOLDER"] = str(OUTPUT_FOLDER)
app.config["TMP_FOLDER"] = str(TMP_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", 700)) * 1024 * 1024

db = SQLAlchemy(app)

# optional imports
try:
    from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip, CompositeAudioClip
    from moviepy.video.fx.all import resize
    MOVIEPY_AVAILABLE = True
except Exception as e:
    log.warning("moviepy not available: %s", e)
    MOVIEPY_AVAILABLE = False

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except Exception:
    log.warning("gTTS not available")
    GTTS_AVAILABLE = False

# Payment config read from env
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_SECRET = os.getenv("PAYPAL_SECRET")
PAYPAL_API_BASE = os.getenv("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com")  # change to live in prod

# ----------------- DB models -----------------
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

# init defaults
with app.app_context():
    db.create_all()
    if not VoiceOption.query.first():
        db.session.add_all([
            VoiceOption(display_name="Female", description="Soft female voice"),
            VoiceOption(display_name="Male", description="Deep voice"),
            VoiceOption(display_name="Child", description="Child voice"),
            VoiceOption(display_name="Neutral", description="Neutral")
        ])
    if not TemplateCatalog.query.first():
        db.session.add_all([
            TemplateCatalog(name="Motivation", category="Inspiration"),
            TemplateCatalog(name="Promo", category="Marketing"),
            TemplateCatalog(name="Explainer", category="Education"),
            TemplateCatalog(name="Cinematic", category="Cinema")
        ])
    if not Plan.query.first():
        db.session.add_all([
            Plan(name="Free", price="0", features="Low quality, 1 render/day"),
            Plan(name="Premium", price="499", features="FullHD, 10 renders/day"),
            Plan(name="Pro", price="999", features="4K, unlimited renders")
        ])
    if not UserProfile.query.filter_by(email="demo@aivantu.com").first():
        db.session.add(UserProfile(email="demo@aivantu.com", name="Demo User", country="India", credits=5))
    db.session.commit()

# ----------------- helpers -----------------
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

# ---------- OPTIONAL: simple renderer (moviepy) ----------
# NOTE: large/slow; in prod use background workers
def create_lip_sync_like_clip(image_path: str, duration: float, size_width: int = 1280):
    if not MOVIEPY_AVAILABLE:
        raise RuntimeError("moviepy not installed")
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
    from moviepy.editor import concatenate_videoclips
    return concatenate_videoclips(clips, method="compose")

def render_video_multi_characters(image_rel_paths: List[str], audio_rel_paths: List[str], output_abs_path: str, quality: str = "HD", bg_music_rel: Optional[str] = None):
    if not MOVIEPY_AVAILABLE:
        raise RuntimeError("moviepy not installed")
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
            log.exception("Failed bg music: %s", e)
    bitrate = "800k"
    if quality and quality.lower() in ("fullhd", "1080", "1080p"):
        bitrate = "2500k"
    if quality and quality.lower() in ("4k", "2160", "2160p"):
        bitrate = "8000k"
    final_video.write_videofile(output_abs_path, fps=24, codec="libx264", audio_codec="aac", bitrate=bitrate)
    final_video.close()
    for a in audios:
        try: a.close()
        except: pass

# ----------------- Routes -----------------
@app.route("/", methods=["GET"])
def index():
    return jsonify({"msg": "AiVantu backend running", "status": "ok"})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "moviepy": MOVIEPY_AVAILABLE,
        "gtts": GTTS_AVAILABLE,
        "db": app.config["SQLALCHEMY_DATABASE_URI"]
    })

# serve uploads & outputs
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/outputs/<path:filename>")
def output_file(filename):
    return send_from_directory(app.config["OUTPUT_FOLDER"], filename)

# profile endpoints
@app.route("/profile/<string:email>", methods=["GET"])
def get_profile(email):
    u = UserProfile.query.filter_by(email=email).first()
    if not u: return jsonify({"error":"not found"}), 404
    return jsonify({"email":u.email,"name":u.name,"country":u.country,"plan":u.plan,"credits":u.credits,"photo":u.photo})

@app.route("/profile", methods=["POST"])
def upsert_profile():
    data = request.get_json(force=True)
    email = data.get("email")
    if not email: return jsonify({"error":"email required"}), 400
    u = UserProfile.query.filter_by(email=email).first()
    if not u:
        u = UserProfile(email=email, name=data.get("name"), country=data.get("country"))
        db.session.add(u)
    else:
        u.name = data.get("name", u.name); u.country = data.get("country", u.country)
    db.session.commit()
    return jsonify({"message":"ok","email":u.email})

# upload endpoint
@app.route("/upload", methods=["POST"])
def upload_endpoint():
    if "file" not in request.files: return jsonify({"error":"no file"}), 400
    f = request.files["file"]
    kind = request.form.get("kind","files")
    if not f or f.filename == "": return jsonify({"error":"invalid file"}), 400
    saved = save_upload(f, kind)
    return jsonify({"saved": saved, "url": url_for("uploaded_file", filename=saved.replace("uploads/",""), _external=True)})

# preview voice (gTTS)
@app.route("/preview_voice", methods=["POST"])
def preview_voice():
    if not GTTS_AVAILABLE:
        return jsonify({"error":"gTTS not available"}), 500
    text = request.form.get("text","Preview from AiVantu")
    lang = request.form.get("lang","hi")
    uid = uuid.uuid4().hex
    out = Path(app.config["TMP_FOLDER"]) / f"preview_{uid}.mp3"
    try:
        gTTS(text, lang=lang).save(str(out))
        dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out), str(dest))
        return jsonify({"audio_url": url_for("uploaded_file", filename=str(Path("audio")/dest.name), _external=True)})
    except Exception as e:
        log.exception("gTTS fail")
        return jsonify({"error":"TTS failed","details":str(e)}), 500

# PayPal helper: get access token
def paypal_get_access_token():
    if not PAYPAL_CLIENT_ID or not PAYPAL_SECRET:
        raise RuntimeError("PayPal credentials not set")
    resp = requests.post(f"{PAYPAL_API_BASE}/v1/oauth2/token",
                         auth=(PAYPAL_CLIENT_ID,PAYPAL_SECRET),
                         data={"grant_type":"client_credentials"})
    resp.raise_for_status()
    return resp.json()["access_token"]

# create PayPal order
@app.route("/create_paypal_order", methods=["POST"])
def create_paypal_order():
    data = request.get_json() or {}
    amount = data.get("amount")
    currency = data.get("currency","USD")
    if not amount: return jsonify({"error":"amount required"}), 400
    try:
        token = paypal_get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type":"application/json"}
        payload = {"intent":"CAPTURE","purchase_units":[{"amount":{"currency_code":currency,"value":str(amount)}}]}
        r = requests.post(f"{PAYPAL_API_BASE}/v2/checkout/orders", headers=headers, json=payload)
        r.raise_for_status()
        return jsonify(r.json())
    except Exception as e:
        log.exception("PayPal create order failed")
        return jsonify({"error":"paypal error","details":str(e)}),500

# capture PayPal order
@app.route("/capture_paypal_order", methods=["POST"])
def capture_paypal_order():
    data = request.get_json() or {}
    order_id = data.get("orderID")
    if not order_id: return jsonify({"error":"orderID required"}),400
    try:
        token = paypal_get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.post(f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture", headers=headers)
        r.raise_for_status()
        res = r.json()
        # Here: update user plan/credits based on order details
        return jsonify(res)
    except Exception as e:
        log.exception("PayPal capture failed")
        return jsonify({"error":"paypal capture failed","details":str(e)}),500

# Razorpay: create order
@app.route("/create_razorpay_order", methods=["POST"])
def create_razorpay_order():
    data = request.get_json() or {}
    amount = data.get("amount")  # in INR rupees or smallest currency? We'll set paisa (INR*100)
    if amount is None:
        return jsonify({"error":"amount required"}),400
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        return jsonify({"error":"razorpay credentials not configured"}),500
    try:
        amount_paisa = int(float(amount)*100)
        payload = {"amount":amount_paisa,"currency":"INR","receipt":f"rcpt_{uuid.uuid4().hex}"}
        r = requests.post("https://api.razorpay.com/v1/orders", auth=(RAZORPAY_KEY_ID,RAZORPAY_KEY_SECRET), json=payload)
        r.raise_for_status()
        return jsonify(r.json())
    except Exception as e:
        log.exception("Razorpay order failed")
        return jsonify({"error":"razorpay error","details":str(e)}),500

# verify razorpay signature (frontend sends payload)
@app.route("/verify_razorpay_payment", methods=["POST"])
def verify_razorpay_payment():
    data = request.get_json() or {}
    # frontend should send: razorpay_order_id, razorpay_payment_id, razorpay_signature
    order_id = data.get("razorpay_order_id"); payment_id = data.get("razorpay_payment_id"); signature = data.get("razorpay_signature")
    if not (order_id and payment_id and signature):
        return jsonify({"error":"missing params"}),400
    # server-side signature verify
    # HMAC SHA256 of order_id|payment_id with RAZORPAY_KEY_SECRET
    import hmac, hashlib
    generated = hmac.new(bytes(RAZORPAY_KEY_SECRET,"utf-8"), (order_id + "|" + payment_id).encode("utf-8"), hashlib.sha256).hexdigest()
    ok = generated == signature
    return jsonify({"ok": ok})

# assistant endpoint (simple)
@app.route("/assistant", methods=["POST"])
def assistant():
    data = request.get_json() or {}
    q = data.get("query","")
    lang = data.get("lang","hi")
    # simple suggestion
    reply = f"AI Suggestion: Make the opening more gripping. You asked: {q}"
    audio_url = None
    if GTTS_AVAILABLE:
        try:
            uid = uuid.uuid4().hex
            out = Path(app.config["TMP_FOLDER"]) / f"assistant_{uid}.mp3"
            gTTS(reply, lang=lang).save(str(out))
            dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(out), str(dest))
            audio_url = url_for("uploaded_file", filename=str(Path("audio")/dest.name), _external=True)
        except Exception:
            audio_url = None
    return jsonify({"reply": reply, "audio_url": audio_url})

# generate video endpoint (synchronous; recommended to run async in production)
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
    - bg_music_file (optional)
    - characters[] image files
    - character_voice_files[] (optional audio files)
    - voice_type[] (optional)
    """
    # validate
    user_email = request.form.get("user_email","demo@aivantu.com")
    title = request.form.get("title") or f"Video_{datetime.utcnow().isoformat()}"
    script = request.form.get("script","")
    template = request.form.get("template","Default")
    quality = request.form.get("quality","HD")
    lang = request.form.get("lang","hi")
    bg_choice = request.form.get("bg_music","")

    video = UserVideo(user_email=user_email, title=title, script=script, template=template, quality=quality, length_type=request.form.get("length_type","short"), background_music=bg_choice, status="rendering")
    db.session.add(video); db.session.commit()
    job_id = f"video_{video.id}"
    log.info("Start job %s", job_id)

    # save images
    image_rel_paths = []
    if "characters" in request.files:
        files = request.files.getlist("characters")
        for f in files:
            if f and allowed_file(f.filename, ALLOWED_IMAGE_EXT):
                image_rel_paths.append(save_upload(f, "characters"))
    if not image_rel_paths:
        # fallback thumbnail / placeholder
        tc = TemplateCatalog.query.filter_by(name=template).first()
        if tc and tc.thumbnail:
            image_rel_paths = [tc.thumbnail]
        else:
            # create placeholder via pillow
            try:
                from PIL import Image
                placeholder = Path(app.config["TMP_FOLDER"]) / f"{job_id}_ph.png"
                img = Image.new("RGB",(1280,720),(245,245,245))
                img.save(placeholder)
                image_rel_paths = [str(placeholder.relative_to(BASE_DIR))]
            except Exception as e:
                log.exception("placeholder failed")
                video.status="failed"; db.session.commit()
                return jsonify({"status":"error","message":"no chars and placeholder failed","details":str(e)}),400

    # bg music
    bg_rel = None
    if "bg_music_file" in request.files:
        f = request.files.get("bg_music_file")
        if f and allowed_file(f.filename, ALLOWED_AUDIO_EXT):
            bg_rel = save_upload(f, "music")
    else:
        if bg_choice:
            p = Path(app.config["UPLOAD_FOLDER"]) / "music" / f"{bg_choice}.mp3"
            if p.exists(): bg_rel = str(Path("music")/p.name)

    # character voice uploads
    char_voice_files = []
    if "character_voice_files" in request.files:
        vfiles = request.files.getlist("character_voice_files")
        for vf in vfiles:
            if vf and allowed_file(vf.filename, ALLOWED_AUDIO_EXT):
                char_voice_files.append(save_upload(vf, "user_voices"))

    # voice types (pad)
    voice_types = request.form.getlist("voice_type")
    while len(voice_types) < len(image_rel_paths):
        voice_types.append(voice_types[0] if voice_types else "Female")

    # split script into parts for characters
    parts = []
    markers = [f"[C{i+1}]:" for i in range(len(image_rel_paths))]
    if any(m in script for m in markers):
        remaining = script
        for m in markers:
            idx = remaining.find(m)
            if idx == -1:
                parts.append("")
                continue
            nxt_positions = [remaining.find(x, idx+1) for x in markers if remaining.find(x, idx+1) != -1]
            next_pos = min(nxt_positions) if nxt_positions else len(remaining)
            parts.append(remaining[idx+len(m):next_pos].strip())
    else:
        lines = [l.strip() for l in script.split("\n") if l.strip()]
        if not lines:
            words = script.split()
            if not words:
                parts = ["Hello from AiVantu"] + [""]*(len(image_rel_paths)-1)
            else:
                per = max(1, len(words)//len(image_rel_paths))
                for i in range(len(image_rel_paths)):
                    chunk = words[i*per:(i+1)*per] if i < len(image_rel_paths)-1 else words[i*per:]
                    parts.append(" ".join(chunk).strip())
        else:
            parts = ["" for _ in range(len(image_rel_paths))]
            for idx,l in enumerate(lines):
                parts[idx % len(image_rel_paths)] += (l + " ")
            parts = [p.strip() for p in parts]
    while len(parts) < len(image_rel_paths):
        parts.append("")

    # build audio per character: uploaded voice has priority else gTTS
    audio_rel_paths = []
    for i in range(len(image_rel_paths)):
        if i < len(char_voice_files):
            audio_rel_paths.append(char_voice_files[i]); continue
        txt = parts[i] if i < len(parts) else ""
        if not txt.strip():
            # create tiny silence via gTTS " " if available
            if GTTS_AVAILABLE:
                try:
                    out = Path(app.config["TMP_FOLDER"]) / f"{job_id}_empty_{i}.mp3"
                    gTTS(" ", lang=lang).save(str(out))
                    dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(out), str(dest))
                    audio_rel_paths.append(str(Path("audio")/dest.name)); continue
                except Exception:
                    pass
            p = Path(app.config["TMP_FOLDER"]) / f"{job_id}_silent_{i}.mp3"
            p.write_bytes(b""); audio_rel_paths.append(str(p.relative_to(BASE_DIR))); continue
        # use gTTS
        if not GTTS_AVAILABLE:
            video.status="failed"; db.session.commit()
            return jsonify({"status":"error","message":"gTTS not available for TTS"}),500
        try:
            uid = uuid.uuid4().hex
            out = Path(app.config["TMP_FOLDER"]) / f"{job_id}_{i}_{uid}.mp3"
            gTTS(txt, lang=lang).save(str(out))
            dest = Path(app.config["UPLOAD_FOLDER"]) / "audio" / out.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(out), str(dest))
            audio_rel_paths.append(str(Path("audio")/dest.name))
        except Exception as e:
            log.exception("TTS failed")
            video.status="failed"; db.session.commit()
            return jsonify({"status":"error","message":"TTS failed","details":str(e)}),500

    # render synchronously (for tests) -> in prod use background worker
    out_name = f"video_{video.id}.mp4"
    out_abs = Path(app.config["OUTPUT_FOLDER"]) / out_name
    try:
        render_video_multi_characters(image_rel_paths, audio_rel_paths, str(out_abs), quality=quality, bg_music_rel=bg_rel)
        video.file_path = str(Path("outputs") / out_name)
        video.status = "done"
        video.meta_json = json.dumps({"script":script,"chars":image_rel_paths,"voices":voice_types,"quality":quality,"created_at":datetime.utcnow().isoformat()})
        db.session.commit()
    except Exception as e:
        log.exception("Render failed")
        video.status="failed"; db.session.commit()
        return jsonify({"status":"error","message":"Render failed","details":str(e)}),500

    return jsonify({"status":"done","video_id":video.id,"download_url": url_for("output_file", filename=out_name, _external=True)}), 200

# gallery
@app.route("/gallery/<string:email>", methods=["GET"])
def gallery(email):
    vids = UserVideo.query.filter_by(user_email=email).order_by(UserVideo.created_at.desc()).all()
    out = []
    for v in vids:
        out.append({"id":v.id,"title":v.title,"status":v.status,"file": v.file_path and url_for("output_file", filename=Path(v.file_path).name, _external=True)})
    return jsonify(out)

# admin status
@app.route("/admin/status", methods=["GET"])
def admin_status():
    counts = {
        "users": UserProfile.query.count(),
        "videos": UserVideo.query.count(),
        "templates": TemplateCatalog.query.count(),
        "voices": VoiceOption.query.count()
    }
    return jsonify(counts)

if __name__ == "__main__":
    port = int(os.getenv("PORT",5000))
    # debug False for prod
    app.run(host="0.0.0.0", port=port, debug=False)
