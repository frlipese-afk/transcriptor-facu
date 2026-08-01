from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from groq import Groq
from supabase import create_client, Client
from fastapi import FastAPI, File, UploadFile, Form, Request, Body
import boto3
import os
import uuid
import subprocess
import glob
import imageio_ffmpeg


app = FastAPI()
# Le decimos a FastAPI dónde están los HTML
templates = Jinja2Templates(directory="templates")

# --- CONFIGURACIÓN ---
client_groq = Groq()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

s3_client = boto3.client('s3',
    endpoint_url=os.environ.get("R2_ENDPOINT_URL"),
    aws_access_key_id=os.environ.get("R2_ACCESS_KEY"),
    aws_secret_access_key=os.environ.get("R2_SECRET_KEY"),
    region_name='auto'
)
BUCKET_NAME = 'transcriptor-audios'
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL")


# --- PÁGINA PRINCIPAL ---
@app.get("/", response_class=HTMLResponse)
async def leer_inicio(request: Request):
    # Solo le pasamos las llaves de Supabase al HTML para que el login funcione
    return templates.TemplateResponse(request, "index.html", {
        "supabase_url": SUPABASE_URL,
        "supabase_key": SUPABASE_KEY
    })


# --- TRANSCRIPCIÓN ---
@app.post("/transcribir", response_class=HTMLResponse)
async def transcribir_audio(email: str = Form(...), audio: UploadFile = File(...)):
    response_db = supabase.table("usuarios").select("creditos").eq("email", email).execute()
    if not response_db.data:
        return "<h3>No estás registrado.</h3><a href='/'>Volver</a>"
    
    creditos = response_db.data[0]['creditos']
    if creditos <= 0:
        return f"<h3>No tenés créditos, {email}.</h3><a href='/'>Volver</a>"

    audio_bytes = await audio.read()
    try:
        extension = audio.filename.split('.')[-1].lower()
        temp_original = f"temp_original.{extension}"
        with open(temp_original, "wb") as f: f.write(audio_bytes)
        
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run([
            ffmpeg_exe, "-i", temp_original, 
            "-f", "segment", "-segment_time", "600", 
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", 
            "temp_chunk_%03d.wav"
        ], check=True, capture_output=True)
        
        chunks = sorted(glob.glob("temp_chunk_*.wav"))
        texto_plano = ""
        texto_html = ""
        
        for i, chunk_filename in enumerate(chunks):
            with open(chunk_filename, "rb") as audio_file:
                response_groq = client_groq.audio.transcriptions.create(
                    model="whisper-large-v3-turbo", 
                    file=audio_file, 
                    response_format="verbose_json"
                )
            
            offset_segundos = i * 600.0
            for segmento in response_groq.segments:
                inicio_real = segmento['start'] + offset_segundos
                minutos = int(inicio_real // 60)
                segundos = int(inicio_real % 60)
                
                texto_plano += f"[{minutos:02d}:{segundos:02d}] {segmento['text']}\n"
                texto_html += f"<span class='minuto' onclick='saltarA({inicio_real})'>[{minutos:02d}:{segundos:02d}]</span> {segmento['text']}<br>"
            
            os.remove(chunk_filename)
        
        if os.path.exists(temp_original): os.remove(temp_original)

        content_type = audio.content_type if audio.content_type and audio.content_type.startswith('audio') else 'audio/mpeg'
        nombre_archivo_nube = f"{uuid.uuid4()}_{audio.filename}"
        s3_client.put_object(Bucket=BUCKET_NAME, Key=nombre_archivo_nube, Body=audio_bytes, ContentType=content_type)
        url_audio = f"{R2_PUBLIC_URL}/{nombre_archivo_nube}"
        
        titulo_limpio = os.path.splitext(audio.filename)[0]
        
        supabase.table("transcripciones").insert({
            "user_email": email,
            "titulo": titulo_limpio,
            "texto": texto_plano,
            "audio_url": url_audio
        }).execute()
    except Exception as e:
        return f"Error procesando el audio: {e}"

    nuevos_creditos = creditos - 1
    supabase.table("usuarios").update({"creditos": nuevos_creditos}).eq("email", email).execute()

    # Mostramos el resultado (Después pasaremos esto a plantilla también, pero por ahora queda así)
    return f"""
    <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Resultado</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f0f2f5; margin: 0; padding: 20px; color: #1a1a1a; }}
                .container {{ max-width: 600px; margin: 20px auto; }}
                .card {{ background: white; border-radius: 16px; padding: 24px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
                h3 {{ margin-top: 0; color: #333; font-size: 22px; }}
                audio {{ width: 100%; margin-bottom: 20px; border-radius: 12px; }}
                .texto {{ white-space: pre-wrap; font-size: 17px; line-height: 1.8; color: #444; }}
                .creditos {{ color: #666; font-size: 14px; margin-top: 20px; border-top: 1px solid #eee; padding-top: 15px; text-align: center; }}
                .btn {{ display: block; width: 100%; padding: 16px; font-size: 17px; border: none; border-radius: 12px; cursor: pointer; font-weight: 600; margin-top: 15px; text-decoration: none; box-sizing: border-box; text-align: center; }}
                .btn-success {{ background: #28a745; color: white; }}
                .btn-back {{ background: #e9ecef; color: #666; }}
                .minuto {{ color: #007bff; cursor: pointer; font-weight: bold; background: #e7f1ff; padding: 3px 8px; border-radius: 6px; margin-right: 5px; display: inline-block; margin-bottom: 5px; font-size: 14px; }}
                .minuto:hover {{ background: #007bff; color: white; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <h3>📝 Transcripción:</h3>
                    <audio id="reproductor" controls src="{url_audio}"></audio>
                    <div class="texto">{texto_html}</div>
                    <div class="creditos">Te quedan <b>{nuevos_creditos}</b> créditos.</div>
                    <a href="/historial?email={email}" class="btn btn-success">📚 Ver mi historial</a>
                    <a href="/" class="btn btn-back">⬅️ Volver a transcribir</a>
                </div>
            </div>
            <script>
                function saltarA(segundos) {{
                    const audio = document.getElementById('reproductor');
                    audio.currentTime = segundos;
                    audio.play();
                }}
            </script>
        </body>
    </html>
    """


# --- HISTORIAL ---
@app.get("/historial", response_class=HTMLResponse)
async def ver_historial(request: Request, email: str):
    response = supabase.table("transcripciones").select("id, titulo, texto, fecha, audio_url").eq("user_email", email).order("fecha", desc=True).execute()
    notas = response.data
    
    notas_procesadas = []
    for nota in notas:
        texto_html = ""
        # Usamos .get() por si la nota no tiene texto (evita el error)
        texto_original = nota.get('texto', '') or ''
        
        for linea in texto_original.split('\n'):
            # Si la línea tiene corchete, intentamos sacarle el minuto
            if linea.startswith('[') and ']' in linea:
                partes = linea.split(']', 1)
                minuto_str = partes[0].replace('[', '').strip()
                try:
                    # Intentamos convertir el minuto a números
                    mins, segs = map(int, minuto_str.split(':'))
                    segundos_totales = mins * 60 + segs
                    texto_html += f"<span class='minuto' onclick='saltarAHistorial({segundos_totales}, {nota['id']})'>[{minuto_str}]</span>{partes[1]}<br>"
                except:
                    # Si falla (ej: no son números), mostramos la línea normal
                    texto_html += f"{linea}<br>"
            else:
                # Si no tiene corchete, la mostramos normal
                texto_html += f"{linea}<br>"
        
        nota['texto_html'] = texto_html
        notas_procesadas.append(nota)

    return templates.TemplateResponse(request, "historial.html", {
        "notas": notas_procesadas,
        "email": email
    })


# --- PANEL DE ADMIN ---
@app.get("/admin-secreto", response_class=HTMLResponse)
async def panel_admin():
    response = supabase.table("usuarios").select("*").execute()
    usuarios = response.data
    tabla_html = ""
    for u in usuarios:
        tabla_html += f"<tr><td>{u['email']}</td><td>{u['creditos']}</td><td><form action='/agregar-creditos' method='post'><input type='hidden' name='email' value='{u['email']}'><input type='number' name='cantidad' value='5' style='width:60px; padding:5px;'><button type='submit' style='padding:5px 10px; background:green; color:white; border:none; border-radius:3px; cursor:pointer;'>Sumar</button></form></td></tr>"

    return f"""
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Admin</title><style>body {{ font-family: Arial; padding: 20px; background: #e9ecef; }} .contenedor {{ max-width: 800px; margin: auto; background: white; padding: 20px; border-radius: 8px; }} table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }} th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }} th {{ background-color: #f2f2f2; }}</style></head>
    <body><div class="contenedor"><h1>Panel de Administración 🛠️</h1><table><tr><th>Email</th><th>Créditos Actuales</th><th>Sumar Créditos</th></tr>{tabla_html}</table><br><h3>Registrar nuevo usuario:</h3><form action='/agregar-creditos' method='post'>Email: <input type='email' name='email' required style='padding:8px;'>Créditos: <input type='number' name='cantidad' value='5' style='width:60px; padding:8px;'><button type='submit' style='padding:8px 15px; background:#007bff; color:white; border:none; border-radius:4px; cursor:pointer;'>Crear y Sumar</button></form></div></body></html>
    """

@app.post("/agregar-creditos")
async def agregar_creditos(email: str = Form(...), cantidad: int = Form(...)):
    res = supabase.table("usuarios").select("creditos").eq("email", email).execute()
    if res.data:
        creditos_actuales = res.data[0]['creditos']
        nuevos = creditos_actuales + cantidad
        supabase.table("usuarios").update({"creditos": nuevos}).eq("email", email).execute()
    else:
        supabase.table("usuarios").insert({"email": email, "creditos": cantidad}).execute()
    
    return "<h3>¡Créditos actualizados! Volvé al panel.</h3><a href='/admin-secreto'>Volver al panel</a>"

    # --- BORRAR TRANSCRIPCIÓN ---
@app.post("/borrar/{transcripcion_id}")
async def borrar_transcripcion(transcripcion_id: int, email: str = Form(...)):
    # 1. Buscamos la nota en Supabase para conseguir el link del audio
    response = supabase.table("transcripciones").select("audio_url").eq("id", transcripcion_id).execute()
    
    if response.data:
        audio_url = response.data[0].get('audio_url', '')
        
        # 2. Si tiene audio, lo borramos de Cloudflare R2
        if audio_url:
            # Agarramos el nombre del archivo (lo que está después de la última barra /)
            nombre_archivo = audio_url.split('/')[-1]
            try:
                s3_client.delete_object(Bucket=BUCKET_NAME, Key=nombre_archivo)
            except Exception as e:
                print(f"Error al borrar audio de R2: {e}")
        
        # 3. Borramos el texto de la base de datos (Supabase)
        supabase.table("transcripciones").delete().eq("id", transcripcion_id).execute()
    
    # 4. Volvemos al historial
    return RedirectResponse(url=f"/historial?email={email}", status_code=303)


# --- EDITAR TÍTULO ---
@app.post("/editar-titulo/{transcripcion_id}")
async def editar_titulo(transcripcion_id: int, data: dict = Body(...)):
    email = data.get("email")
    nuevo_titulo = data.get("titulo")
    nuevo_titulo = os.path.splitext(nuevo_titulo)[0]
    
    # Actualizamos en Supabase
    supabase.table("transcripciones").update({"titulo": nuevo_titulo}).eq("id", transcripcion_id).eq("user_email", email).execute()
    
     # Le respondemos a JavaScript que salió todo bien
    return {"titulo": nuevo_titulo}