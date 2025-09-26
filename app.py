# app.py — AiVantu Phase-3 FINAL (multi-char, multi-voice, SQLite only)

import os, uuid, json, shutil, logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from flask import Flask, render_template_string, request, redirect, url_for, flash, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

# logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aivantu")

# ---------- Config ----------
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER, OUTPUT_FOLDER, TMP_FOLDER = BASE_DIR/"uploads", BASE_DIR/"outputs", BASE_DIR/"tmp"
for p in (UPLOAD_FOLDER, OUTPUT_FOLDER, TMP_FOLDER): p.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXT, ALLOWED_AUDIO_EXT = {"png","jpg","jpeg","gif","webp"}, {"mp3","wav","ogg","m4a"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("APP_SECRET_KEY","aivantu-secret")
# Force SQLite only
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{str(BASE_DIR / 'data.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"], app.config["OUTPUT_FOLDER"], app.config["TMP_FOLDER"] = str(UPLOAD_FOLDER), str(OUTPUT_FOLDER), str(TMP_FOLDER)
db = SQLAlchemy(app)

# ---------- Models ----------
class UserVideo(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    user_email=db.Column(db.String(255),nullable=False)
    title=db.Column(db.String(255)); script=db.Column(db.Text); template=db.Column(db.String(255))
    voices=db.Column(db.String(255)); quality=db.Column(db.String(20)); length_type=db.Column(db.String(20))
    background_music=db.Column(db.String(255)); created_at=db.Column(db.DateTime,default=datetime.utcnow)
    file_path=db.Column(db.String(1024)); status=db.Column(db.String(50),default="ready"); meta_json=db.Column(db.Text)

class TemplateCatalog(db.Model): id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(255)); category=db.Column(db.String(100)); thumbnail=db.Column(db.String(1024))
class VoiceOption(db.Model): id=db.Column(db.Integer,primary_key=True); display_name=db.Column(db.String(255)); description=db.Column(db.String(512))
class UserProfile(db.Model): id=db.Column(db.Integer,primary_key=True); email=db.Column(db.String(255),unique=True); name=db.Column(db.String(100)); country=db.Column(db.String(100)); photo=db.Column(db.String(255)); plan=db.Column(db.String(50),default="Free")
class UserCharacter(db.Model): id=db.Column(db.Integer,primary_key=True); user_email=db.Column(db.String(255),nullable=False); name=db.Column(db.String(100),default="My Character"); photo_path=db.Column(db.String(1024)); voice_path=db.Column(db.String(1024)); ai_style=db.Column(db.String(50)); mood=db.Column(db.String(50)); is_locked=db.Column(db.Boolean,default=True); created_at=db.Column(db.DateTime,default=datetime.utcnow)
class CharacterBundle(db.Model): id=db.Column(db.Integer,primary_key=True); user_email=db.Column(db.String(255),nullable=False); name=db.Column(db.String(100),default="Bundle"); characters_json=db.Column(db.Text); created_at=db.Column(db.DateTime,default=datetime.utcnow)
class Plan(db.Model): id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(100)); price=db.Column(db.String(50)); features=db.Column(db.String(255))

# ---------- DB init ----------
with app.app_context():
    db.create_all()
    if not VoiceOption.query.first(): db.session.add_all([VoiceOption(display_name="Female",description="Soft female voice"),VoiceOption(display_name="Male",description="Deep male voice"),VoiceOption(display_name="Child",description="Child voice"),VoiceOption(display_name="Celebrity",description="Celebrity-like demo")])
    if not TemplateCatalog.query.first(): db.session.add_all([TemplateCatalog(name="Motivation",category="Inspiration"),TemplateCatalog(name="Promo",category="Marketing"),TemplateCatalog(name="Explainer",category="Education"),TemplateCatalog(name="Kids",category="Cartoon"),TemplateCatalog(name="Event",category="Celebration")])
    if not Plan.query.first(): db.session.add_all([Plan(name="Free",price="0",features="Low quality, 1 render/day"),Plan(name="Premium",price="499",features="FullHD, 10 renders/day"),Plan(name="Pro",price="999",features="4K, unlimited renders")])
    if not UserProfile.query.filter_by(email="demo@aivantu.com").first(): db.session.add(UserProfile(email="demo@aivantu.com",name="Demo User",country="India"))
    db.session.commit()

# ---------- Helpers ----------
def allowed_file(fn,allowed): return "." in fn and fn.rsplit(".",1)[1].lower() in allowed
def save_upload(fs,sub=""): fn=secure_filename(fs.filename); ext=fn.rsplit(".",1)[1].lower() if "." in fn else ""; uid=uuid.uuid4().hex; dn=f"{uid}.{ext}" if ext else uid; folder=Path(app.config["UPLOAD_FOLDER"])/sub; folder.mkdir(parents=True,exist_ok=True); dest=folder/dn; fs.save(dest); return str(dest.relative_to(BASE_DIR))
def _abs(p): return str((BASE_DIR/p).resolve()) if not str(p).startswith(str(BASE_DIR)) else str(p)

# ---------- Rendering ----------
def create_lip_sync_like_clip(img,dur):
    from moviepy.editor import ImageClip,concatenate_videoclips; from moviepy.video.fx.all import resize
    abs_img=_abs(img); base=ImageClip(abs_img).set_duration(dur).resize(width=1280); zoom=base.fx(resize,0.98)
    seg=0.12; t=0; clips=[]; toggle=False
    while t<dur-1e-6: d=min(seg,dur-t); clips.append((zoom if toggle else base).set_duration(d)); toggle=not toggle; t+=d
    return concatenate_videoclips(clips,method="compose")

def render_video_multi(imgs,audios,out,quality="HD",bg=None):
    from moviepy.editor import AudioFileClip,concatenate_videoclips,CompositeAudioClip,concatenate_audioclips
    out_abs=_abs(out); clips=[]; audio_objs=[]; n=min(len(imgs),len(audios))
    for i in range(n):
        ac=AudioFileClip(_abs(audios[i])); dur=ac.duration if ac.duration>0.1 else 2
        vc=create_lip_sync_like_clip(imgs[i],dur).set_audio(ac); clips.append(vc); audio_objs.append(ac)
    final=concatenate_videoclips(clips,method="compose")
    if bg:
        bgc=AudioFileClip(_abs(bg)); 
        if bgc.duration<final.duration: bgc=concatenate_audioclips([bgc]*((int(final.duration/bgc.duration))+1)).subclip(0,final.duration)
        else: bgc=bgc.subclip(0,final.duration)
        final=final.set_audio(CompositeAudioClip([final.audio,bgc.volumex(0.12)]))
    br="800k"; 
    if quality.lower() in ("fullhd","1080","1080p"): br="2500k"
    if quality.lower() in ("4k","2160","2160p"): br="8000k"
    final.write_videofile(out_abs,fps=24,codec="libx264",audio_codec="aac",bitrate=br)
    final.close(); [a.close() for a in audio_objs]

# ---------- Routes ----------
@app.route("/") 
def home(): return jsonify({"status":"ok","msg":"AiVantu Phase3 backend running"})

@app.route("/generate_video",methods=["POST"])
def generate_video():
    from gtts import gTTS
    demo_email=request.form.get("user_email","demo@aivantu.com"); title=request.form.get("title") or f"Video {datetime.utcnow()}"; script=request.form.get("script",""); template=request.form.get("template","Default"); quality=request.form.get("quality","HD"); length=request.form.get("length_type","short"); lang=request.form.get("lang","hi")
    v=UserVideo(user_email=demo_email,title=title,script=script,template=template,quality=quality,length_type=length,status="rendering"); db.session.add(v); db.session.commit(); job=f"video_{v.id}"
    imgs=[]; auds=[]
    # chars
    if "characters" in request.files: 
        for f in request.files.getlist("characters"): 
            if allowed_file(f.filename,ALLOWED_IMAGE_EXT): imgs.append(save_upload(f,"chars"))
    if not imgs: from PIL import Image; ph=Path(app.config["TMP_FOLDER"])/f"{job}_ph.png"; Image.new("RGB",(1280,720),(240,240,240)).save(ph); imgs=[str(ph.relative_to(BASE_DIR))]
    # voices
    char_voice=[]; 
    if "character_voice_files" in request.files:
        for f in request.files.getlist("character_voice_files"): 
            if allowed_file(f.filename,ALLOWED_AUDIO_EXT): char_voice.append(save_upload(f,"voices"))
    voice_types=request.form.getlist("voice_type") or ["Female"]; 
    while len(voice_types)<len(imgs): voice_types.append(voice_types[0])
    # split script
    parts=[]; markers=[f"[C{i+1}:" for i in range(len(imgs))]
    if any(m in script for m in markers):
        for i in range(len(imgs)):
            m=f"[C{i+1}:"; idx=script.find(m); 
            if idx!=-1: nxt=min([script.find(x,idx+1) for x in markers if script.find(x,idx+1)!=-1]+[len(script)]); parts.append(script[idx+len(m):nxt].strip())
    if not parts: # evenly split
        words=script.split(); chunk=max(1,len(words)//len(imgs)); 
        for i in range(0,len(words),chunk): parts.append(" ".join(words[i:i+chunk]))
    while len(parts)<len(imgs): parts.append("")
    # prepare audios
    for i in range(len(imgs)):
        if i<len(char_voice): auds.append(char_voice[i])
        else:
            uid=uuid.uuid4().hex; fn=Path(app.config["UPLOAD_FOLDER"])/"audio"/f"{job}_{uid}.mp3"; fn.parent.mkdir(parents=True,exist_ok=True); gTTS(parts[i] or " ",lang=lang).save(fn); auds.append(str(fn.relative_to(BASE_DIR)))
    # bg music
    bg=None; 
    if "bg_music_file" in request.files: 
        f=request.files["bg_music_file"]; 
        if allowed_file(f.filename,ALLOWED_AUDIO_EXT): bg=save_upload(f,"music")
    out=f"outputs/{job}.mp4"; 
    try: render_video_multi(imgs,auds,out,quality,bg); v.file_path=out; v.status="done"; db.session.commit()
    except Exception as e: log.exception("Render fail"); v.status="failed"; db.session.commit(); return jsonify({"error":"render fail","details":str(e)}),500
    return jsonify({"status":"ok","download_url":url_for('output_file',filename=Path(out).name)})

@app.route("/outputs/<path:fn>") 
def output_file(fn): return send_from_directory(app.config["OUTPUT_FOLDER"],fn)

if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.getenv("PORT",5000)),debug=False)
