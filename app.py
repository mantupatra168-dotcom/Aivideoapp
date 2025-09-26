# app.py — AiVantu Phase-3 Production Final
# 🚀 Features: Video Generator + Payments + Gallery + Assistant (without login/register)

import os, uuid, json, shutil, logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from flask import Flask, request, jsonify, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aivantu")

# ---------- Config ----------
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER, OUTPUT_FOLDER, TMP_FOLDER = BASE_DIR/"uploads", BASE_DIR/"outputs", BASE_DIR/"tmp"
for p in (UPLOAD_FOLDER, OUTPUT_FOLDER, TMP_FOLDER): p.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXT = {"png","jpg","jpeg","gif","webp"}
ALLOWED_AUDIO_EXT = {"mp3","wav","ogg","m4a"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("APP_SECRET_KEY","aivantu-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/data.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"], app.config["OUTPUT_FOLDER"], app.config["TMP_FOLDER"] = str(UPLOAD_FOLDER), str(OUTPUT_FOLDER), str(TMP_FOLDER)
db = SQLAlchemy(app)

# ---------- Models ----------
class UserVideo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(255))
    script = db.Column(db.Text)
    template = db.Column(db.String(255))
    quality = db.Column(db.String(20))
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
    plan = db.Column(db.String(50), default="Free")

class Plan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    price = db.Column(db.String(50))
    features = db.Column(db.String(255))

# ---------- DB init ----------
with app.app_context():
    db.create_all()
    if not VoiceOption.query.first():
        db.session.add_all([
            VoiceOption(display_name="Female", description="Soft female voice"),
            VoiceOption(display_name="Male", description="Deep male voice"),
            VoiceOption(display_name="Child", description="Child voice")
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
    db.session.commit()

# ---------- Helpers ----------
def allowed_file(filename:str, allowed:set)->bool:
    return "." in filename and filename.rsplit(".",1)[1].lower() in allowed

def save_upload(file_storage, subfolder="")->str:
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit(".",1)[1].lower() if "." in filename else ""
    uid = uuid.uuid4().hex
    dest_name = f"{uid}.{ext}" if ext else uid
    folder = Path(app.config["UPLOAD_FOLDER"])/subfolder; folder.mkdir(parents=True,exist_ok=True)
    dest = folder/dest_name; file_storage.save(dest)
    return str(dest.relative_to(BASE_DIR))

def _abs_path(rel_or_abs:str)->str:
    p=Path(rel_or_abs)
    return str((BASE_DIR/rel_or_abs).resolve()) if not p.is_absolute() else str(p.resolve())

# ---------- Rendering ----------
def create_lip_sync_like_clip(image_path:str,duration:float):
    from moviepy.editor import ImageClip,concatenate_videoclips
    from moviepy.video.fx.all import resize
    base=ImageClip(_abs_path(image_path)).set_duration(duration).resize(width=1280)
    small=base.fx(resize,0.98); seg=0.12; clips=[];t=0;toggle=False
    while t<duration-1e-6:
        seg_d=min(seg,duration-t)
        clips.append((small if toggle else base).set_duration(seg_d))
        toggle=not toggle;t+=seg_d
    return concatenate_videoclips(clips,method="compose")

def render_video(image_paths:List[str],audio_paths:List[str],out_path:str,quality="HD",bg_music=None):
    from moviepy.editor import AudioFileClip,concatenate_videoclips,CompositeAudioClip
    clips=[];audios=[];n=min(len(image_paths),len(audio_paths))
    for i in range(n):
        aud=AudioFileClip(_abs_path(audio_paths[i])); audios.append(aud)
        clip=create_lip_sync_like_clip(image_paths[i],aud.duration or 2.0).set_audio(aud);clips.append(clip)
    final=concatenate_videoclips(clips,method="compose")
    if bg_music:
        try:
            bg=AudioFileClip(_abs_path(bg_music)).volumex(0.12)
            if bg.duration<final.duration: from moviepy.editor import concatenate_audioclips; bg=concatenate_audioclips([bg]*int(final.duration/bg.duration+1)).subclip(0,final.duration)
            else: bg=bg.subclip(0,final.duration)
            final=final.set_audio(CompositeAudioClip([final.audio,bg]))
        except Exception as e: log.error(f"BG music fail: {e}")
    bitrate="2500k" if "full" in quality.lower() else "8000k" if "4k" in quality.lower() else "800k"
    final.write_videofile(_abs_path(out_path),fps=24,codec="libx264",audio_codec="aac",bitrate=bitrate)
    final.close();[a.close() for a in audios]

# ---------- Routes ----------
@app.route("/")
def home(): return jsonify({"msg":"AiVantu Phase-3 backend running","status":"ok"})

@app.route("/uploads/<path:filename>")
def uploaded_file(filename): return send_from_directory(app.config["UPLOAD_FOLDER"],filename)

@app.route("/outputs/<path:filename>")
def output_file(filename): return send_from_directory(app.config["OUTPUT_FOLDER"],filename)

@app.route("/preview_voice",methods=["POST"])
def preview_voice():
    text=request.form.get("text","Preview");lang=request.form.get("lang","hi")
    try:
        from gtts import gTTS;uid=uuid.uuid4().hex;out=Path(app.config["TMP_FOLDER"])/f"pv_{uid}.mp3"
        gTTS(text,lang=lang).save(str(out));dest=Path(app.config["UPLOAD_FOLDER"])/"audio"/out.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(out),dest)
        return jsonify({"audio_url":url_for("uploaded_file",filename=f"audio/{dest.name}")})
    except Exception as e: return jsonify({"error":"TTS failed","details":str(e)}),500

@app.route("/assistant",methods=["POST"])
def assistant():
    q=(request.json or {}).get("query","");lang=(request.json or {}).get("lang","hi")
    reply=f"AI Suggestion: Add CTA in script. Query: {q}"
    return jsonify({"reply":reply})

@app.route("/generate_video",methods=["POST"])
def generate_video():
    email=request.form.get("user_email","demo@aivantu.com");title=request.form.get("title","Untitled")
    script=request.form.get("script","Hello from AiVantu");quality=request.form.get("quality","HD");lang=request.form.get("lang","hi")
    vid=UserVideo(user_email=email,title=title,script=script,quality=quality,status="rendering");db.session.add(vid);db.session.commit()
    imgs=[save_upload(f,"chars") for f in request.files.getlist("characters") if allowed_file(f.filename,ALLOWED_IMAGE_EXT)]
    if not imgs: from PIL import Image;ph=Path(app.config["TMP_FOLDER"])/f"ph_{vid.id}.png";Image.new("RGB",(1280,720),(245,245,245)).save(ph);imgs=[str(ph.relative_to(BASE_DIR))]
    texts=[script];audios=[]
    for i,t in enumerate(texts):
        from gtts import gTTS;out=Path(app.config["TMP_FOLDER"])/f"{vid.id}_{i}.mp3";gTTS(t,lang=lang).save(out)
        dest=Path(app.config["UPLOAD_FOLDER"])/"audio"/out.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.move(out,dest);audios.append(str(Path("audio")/dest.name))
    out_rel=f"outputs/video_{vid.id}.mp4";out_abs=Path(app.config["OUTPUT_FOLDER"])/f"video_{vid.id}.mp4"
    render_video(imgs,audios,str(out_abs),quality)
    vid.file_path=out_rel;vid.status="done";db.session.commit()
    return jsonify({"status":"done","download_url":url_for("output_file",filename=f"video_{vid.id}.mp4",_external=True)})

# ---------- Run ----------
if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT",5000)),debug=False)
