# app.py — AiVantu Phase-3 Final (Production)
import os, uuid, json, shutil, logging, random
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from flask import Flask, request, jsonify, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

# Logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aivantu")

# ---------- Config ----------
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER, OUTPUT_FOLDER, TMP_FOLDER = BASE_DIR / "uploads", BASE_DIR / "outputs", BASE_DIR / "tmp"
for p in (UPLOAD_FOLDER, OUTPUT_FOLDER, TMP_FOLDER): p.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXT = {"png","jpg","jpeg","gif","webp"}
ALLOWED_AUDIO_EXT = {"mp3","wav","ogg","m4a"}
ALLOWED_VIDEO_EXT = {"mp4","mov","mkv","webm"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("APP_SECRET_KEY","aivantu-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", f"sqlite:///{str(BASE_DIR/'data.db')}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"], app.config["OUTPUT_FOLDER"], app.config["TMP_FOLDER"] = str(UPLOAD_FOLDER), str(OUTPUT_FOLDER), str(TMP_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB",700))*1024*1024
db = SQLAlchemy(app)

# ---------- Models ----------
class UserVideo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(255),nullable=False)
    title = db.Column(db.String(255)); script = db.Column(db.Text); template = db.Column(db.String(255))
    voices = db.Column(db.String(255)); quality = db.Column(db.String(20)); length_type = db.Column(db.String(20))
    background_music = db.Column(db.String(255)); created_at = db.Column(db.DateTime,default=datetime.utcnow)
    file_path = db.Column(db.String(1024)); status = db.Column(db.String(50),default="ready")
    meta_json = db.Column(db.Text)

class TemplateCatalog(db.Model): id = db.Column(db.Integer,primary_key=True); name=db.Column(db.String(255)); category=db.Column(db.String(100)); thumbnail=db.Column(db.String(1024))
class VoiceOption(db.Model): id=db.Column(db.Integer,primary_key=True); display_name=db.Column(db.String(255)); description=db.Column(db.String(512))
class UserProfile(db.Model): id=db.Column(db.Integer,primary_key=True); email=db.Column(db.String(255),unique=True); name=db.Column(db.String(100)); country=db.Column(db.String(100)); photo=db.Column(db.String(255)); plan=db.Column(db.String(50),default="Free")
class UserCharacter(db.Model): id=db.Column(db.Integer,primary_key=True); user_email=db.Column(db.String(255),nullable=False); name=db.Column(db.String(100),default="My Character"); photo_path=db.Column(db.String(1024)); voice_path=db.Column(db.String(1024)); ai_style=db.Column(db.String(50)); mood=db.Column(db.String(50)); is_locked=db.Column(db.Boolean,default=True); created_at=db.Column(db.DateTime,default=datetime.utcnow)
class Plan(db.Model): id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(100)); price=db.Column(db.String(50)); features=db.Column(db.String(255))

# ---------- Init Defaults ----------
with app.app_context():
    db.create_all()
    if not VoiceOption.query.first():
        db.session.add_all([
            VoiceOption(display_name="Female",description="Soft female voice"),
            VoiceOption(display_name="Male",description="Deep male voice"),
            VoiceOption(display_name="Child",description="Child voice"),
            VoiceOption(display_name="Celebrity",description="Celebrity-like demo")
        ])
    if not TemplateCatalog.query.first():
        db.session.add_all([
            TemplateCatalog(name="Motivation",category="Inspiration"),
            TemplateCatalog(name="Promo",category="Marketing"),
            TemplateCatalog(name="Explainer",category="Education"),
            TemplateCatalog(name="Kids",category="Cartoon"),
            TemplateCatalog(name="Event",category="Celebration")
        ])
    if not Plan.query.first():
        db.session.add_all([
            Plan(name="Free",price="0",features="Low quality, 1 render/day"),
            Plan(name="Premium",price="499",features="FullHD, 10 renders/day"),
            Plan(name="Pro",price="999",features="4K, unlimited renders")
        ])
    if not UserProfile.query.filter_by(email="demo@aivantu.com").first():
        db.session.add(UserProfile(email="demo@aivantu.com",name="Demo User",country="India"))
    db.session.commit()

# ---------- Helpers ----------
def allowed_file(filename:str,allowed:set)->bool: return "." in filename and filename.rsplit(".",1)[1].lower() in allowed
def save_upload(file_storage,subfolder="")->str:
    filename=secure_filename(file_storage.filename); ext=filename.rsplit(".",1)[1].lower() if "." in filename else ""; uid=uuid.uuid4().hex
    dest_name=f"{uid}.{ext}" if ext else uid; folder=Path(app.config["UPLOAD_FOLDER"])/subfolder; folder.mkdir(parents=True,exist_ok=True)
    dest=folder/dest_name; file_storage.save(dest); return str(dest.relative_to(BASE_DIR))
def _abs_path(p): p=Path(p); return str((BASE_DIR/p).resolve() if not p.is_absolute() else p.resolve())

# ---------- Video FX ----------
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip, CompositeAudioClip
from moviepy.video.fx.all import resize

def create_lip_sync_like_clip(img,dur,w=1280):
    base=ImageClip(_abs_path(img)).set_duration(dur).resize(width=w); small=base.fx(resize,0.98)
    seg,clips,t,flag=0.12,[],0.0,False
    while t<dur-1e-6: d=min(seg,dur-t); clips.append((small if flag else base).set_duration(d)); flag=not flag; t+=d
    return concatenate_videoclips(clips,method="compose")

def create_cinematic_shot(img,dur,style="zoom",w=1280):
    base=ImageClip(_abs_path(img)).set_duration(dur).resize(width=w)
    if style=="zoom": return base.resize(lambda t:1+0.02*t).set_duration(dur)
    if style=="pan_left": return base.crop(x1=0,y1=0,x2=w-50,y2=720).set_duration(dur)
    if style=="pan_right": return base.crop(x1=50,y1=0,x2=w,y2=720).set_duration(dur)
    if style=="tilt": return base.resize(1.05).set_position(("center","top")).set_duration(dur)
    return base.set_duration(dur)

def render_video_multi_characters(images:List[str],audios:List[str],out:str,quality="HD",bg_music=None,cinematic=False):
    clips,audios_clips=[],[]
    styles=["zoom","pan_left","pan_right","tilt"]
    n=min(len(images),len(audios))
    if n==0: raise ValueError("No data")
    for i in range(n):
        audio=AudioFileClip(_abs_path(audios[i])); audios_clips.append(audio); dur=audio.duration if audio.duration>0.1 else 2.0
        clip=create_cinematic_shot(images[i],dur,random.choice(styles)) if cinematic else create_lip_sync_like_clip(images[i],dur)
        clips.append(clip.set_audio(audio))
    final=concatenate_videoclips(clips,method="compose")
    if bg_music:
        try:
            bg=AudioFileClip(_abs_path(bg_music))
            if bg.duration<final.duration:
                from moviepy.editor import concatenate_audioclips
                bg=concatenate_audioclips([bg]* (int(final.duration/bg.duration)+1)).subclip(0,final.duration)
            else: bg=bg.subclip(0,final.duration)
            bg=bg.volumex(0.12); final=final.set_audio(CompositeAudioClip([final.audio,bg]))
        except: pass
    bitrate={"hd":"800k","fullhd":"2500k","1080":"2500k","4k":"8000k","2160":"8000k"}.get(quality.lower(),"800k")
    final.write_videofile(_abs_path(out),fps=24,codec="libx264",audio_codec="aac",bitrate=bitrate); final.close()
    for a in audios_clips: 
        try:a.close()
        except:pass

# ---------- Routes ----------
@app.route("/"); 
def home(): return jsonify({"status":"ok","msg":"AiVantu Phase3 Production Backend"})

@app.route("/uploads/<path:f>"); 
def uploaded_file(f): return send_from_directory(app.config["UPLOAD_FOLDER"],f)

@app.route("/outputs/<path:f>"); 
def output_file(f): return send_from_directory(app.config["OUTPUT_FOLDER"],f)

# ---------- API ----------
@app.route("/api/suggest_template",methods=["POST"])
def suggest(): 
    s=(request.json or {}).get("script","").lower()
    if not s.strip(): return jsonify({"suggestion":"Default"}),200
    if any(k in s for k in["promo","buy","sale"]): return jsonify({"suggestion":"Promo"}),200
    if any(k in s for k in["thank","congrats","birthday"]): return jsonify({"suggestion":"Event"}),200
    if any(k in s for k in["tutorial","explain","guide"]): return jsonify({"suggestion":"Explainer"}),200
    if len(s.split())<20: return jsonify({"suggestion":"Short-Clip"}),200
    return jsonify({"suggestion":"Narration"}),200

@app.route("/preview_voice",methods=["POST"])
def preview_voice():
    from gtts import gTTS
    text=request.form.get("text","Preview from AiVantu"); lang=request.form.get("lang","hi")
    uid=uuid.uuid4().hex; out=Path(app.config["TMP_FOLDER"])/f"preview_{uid}.mp3"; gTTS(text,lang=lang).save(str(out))
    dest=Path(app.config["UPLOAD_FOLDER"])/"audio"/out.name; dest.parent.mkdir(parents=True,exist_ok=True); shutil.move(str(out),dest)
    return jsonify({"audio_url":url_for("uploaded_file",filename=str(Path("audio")/dest.name))})

@app.route("/assistant",methods=["POST"])
def assistant():
    from gtts import gTTS
    q=(request.json or {}).get("query",""); lang=(request.json or {}).get("lang","hi")
    reply=f"AI Suggestion: Add energy and CTA. You asked: {q}"
    uid=uuid.uuid4().hex; out=Path(app.config["TMP_FOLDER"])/f"assistant_{uid}.mp3"; gTTS(reply,lang=lang).save(str(out))
    dest=Path(app.config["UPLOAD_FOLDER"])/"audio"/out.name; dest.parent.mkdir(parents=True,exist_ok=True); shutil.move(str(out),dest)
    return jsonify({"reply":reply,"audio_url":url_for("uploaded_file",filename=str(Path("audio")/dest.name))})

@app.route("/generate_video",methods=["POST"])
def generate_video():
    demo_user=request.form.get("user_email","demo@aivantu.com"); title=request.form.get("title") or f"Video {datetime.utcnow().isoformat()}"
    script=request.form.get("script",""); quality=request.form.get("quality","HD"); lang=request.form.get("lang","hi")
    template=request.form.get("template","Default"); length_type=request.form.get("length_type","short"); bg_music_choice=request.form.get("bg_music","")
    cinematic=request.form.get("cinematic","false").lower()=="true"
    video=UserVideo(user_email=demo_user,title=title,script=script,template=template,quality=quality,length_type=length_type,background_music=bg_music_choice,status="rendering")
    db.session.add(video); db.session.commit(); job=f"video_{video.id}"
    # characters
    imgs=[]; 
    if "characters" in request.files:
        for f in request.files.getlist("characters"):
            if f and allowed_file(f.filename,ALLOWED_IMAGE_EXT): imgs.append(save_upload(f,"characters"))
    if not imgs: 
        from PIL import Image
        ph=Path(app.config["TMP_FOLDER"])/f"{job}_ph.png"; Image.new("RGB",(1280,720),(245,245,245)).save(ph); imgs=[str(ph.relative_to(BASE_DIR))]
    # bg music
    bg=None; f=request.files.get("bg_music_file")
    if f and allowed_file(f.filename,ALLOWED_AUDIO_EXT): bg=save_upload(f,"music")
    elif bg_music_choice: 
        p=Path(app.config["UPLOAD_FOLDER"])/"music"/f"{bg_music_choice}.mp3"
        if p.exists(): bg=str(Path("music")/p.name)
    # voices
    voice_files=[]; 
    if "character_voice_files" in request.files:
        for vf in request.files.getlist("character_voice_files"):
            if vf and allowed_file(vf.filename,ALLOWED_AUDIO_EXT): voice_files.append(save_upload(vf,"user_voices"))
    texts=[script] if len(imgs)==1 else script.split("\n")[:len(imgs)]
    audios=[]
    for i,img in enumerate(imgs):
        if i<len(voice_files): audios.append(voice_files[i]); continue
        from gtts import gTTS
        t=texts[i] if i<len(texts) else "Hello from AiVantu"; uid=uuid.uuid4().hex; out=Path(app.config["TMP_FOLDER"])/f"{job}_{i}_{uid}.mp3"; gTTS(t,lang=lang).save(str(out))
        dest=Path(app.config["UPLOAD_FOLDER"])/"audio"/out.name; dest.parent.mkdir(parents=True,exist_ok=True); shutil.move(str(out),dest); audios.append(str(Path("audio")/dest.name))
    out_rel=Path("outputs")/f"video_{video.id}.mp4"; out_abs=Path(app.config["OUTPUT_FOLDER"])/out_rel.name
    try:
        render_video_multi_characters(imgs,audios,str(out_abs),quality=quality,bg_music=bg,cinematic=cinematic)
        video.file_path=str(out_rel); video.status="done"; db.session.commit()
        return jsonify({"status":"done","video_id":video.id,"download_url":url_for("output_file",filename=out_rel.name,_external=True)})
    except Exception as e:
        log.exception("Render failed"); video.status="failed"; db.session.commit()
        return jsonify({"status":"error","message":"Render failed","details":str(e)}),500

# ---------- Run ----------
if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.getenv("PORT",5000)),debug=False)
