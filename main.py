from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import HTMLResponse
from groq import Groq
from supabase import create_client, Client
import boto3
import os
import uuid
import subprocess
import glob
import imageio_ffmpeg

app = FastAPI()

# --- CONFIGURACIÓN DE SERVICIOS ---
client_groq = Groq()

# Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Cloudflare R2
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
async def leer_inicio():
    return f"""
    <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Transcriptor Facu</title>
            <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f0f2f5; margin: 0; padding: 20px; color: #1a1a1a; }}
                .container {{ max-width: 500px; margin: 20px auto; }}
                .card {{ background: white; border-radius: 16px; padding: 30px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); text-align: center; }}
                h1 {{ font-size: 28px; margin-bottom: 20px; color: #333; }}
                p {{ color: #666; font-size: 16px; }}
                .btn {{ display: block; width: 100%; padding: 16px; font-size: 17px; border: none; border-radius: 12px; cursor: pointer; font-weight: 600; margin-top: 15px; text-decoration: none; box-sizing: border-box; }}
                .btn-google {{ background: #fff; color: #333; border: 1px solid #ddd; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .btn-google:hover {{ background: #f8f8f8; }}
                .btn-primary {{ background: #007bff; color: white; }}
                .btn-success {{ background: #28a745; color: white; }}
                .btn-secondary {{ background: #e9ecef; color: #666; }}
                input[type="file"] {{ width: 100%; padding: 15px; margin: 20px 0; border: 2px dashed #ccc; border-radius: 12px; background: #fafafa; box-sizing: border-box; }}
                input[type="hidden"] {{ display: none; }}
                .creditos-box {{ background: #e7f1ff; color: #007bff; padding: 10px; border-radius: 8px; font-weight: bold; margin: 15px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <h1>🎙️ Transcriptor Facu</h1>
                    
                    <div id="login-box">
                        <p>Ingresá para empezar a transcribir tus clases</p>
                        <button class="btn btn-google" onclick="loginConGoogle()">
                            <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/c/c1/Google_%22G%22_logo.svg/24px-Google_%22G%22_logo.svg.png" style="vertical-align:middle; margin-right:10px;" alt="Google">Iniciar sesión con Google
                        </button>
                    </div>

                    <div id="app-box" style="display: none;">
                        <p>Hola, <b id="user-email"></b> 👋</p>
                        <div class="creditos-box">
                            Créditos: <span id="creditos">Cargando...</span>
                        </div>
                        <form action="/transcribir" method="post" enctype="multipart/form-data">
                            <input type="hidden" name="email" id="hidden-email">
                            <input type="file" name="audio" accept="audio/*" required>
                            <button class="btn btn-primary" type="submit">Subir y Transcribir</button>
                        </form>
                        <a id="historial-link" href="#" class="btn btn-success">📚 Ver mi historial</a>
                        <button class="btn btn-secondary" onclick="cerrarSesion()">Cerrar sesión</button>
                    </div>
                </div>
            </div>

            <script>
                const supabaseClient = supabase.createClient('{SUPABASE_URL}', '{SUPABASE_KEY}');
                
                async function checkUser() {{
                    const {{ data: {{ session }} }} = await supabaseClient.auth.getSession();
                    if (session) {{ mostrarApp(session.user.email); }}
                }}

                async function loginConGoogle() {{
                    await supabaseClient.auth.signInWithOAuth({{
                        provider: 'google',
                        options: {{ redirectTo: window.location.origin }}
                    }});
                }}

                async function mostrarApp(email) {{
                    document.getElementById('login-box').style.display = 'none';
                    document.getElementById('app-box').style.display = 'block';
                    document.getElementById('user-email').innerText = email;
                    document.getElementById('hidden-email').value = email;
                    document.getElementById('historial-link').href = '/historial?email=' + email;
                    try {{
                        let res = await fetch(`https://tfjhtxentxhufvdckkin.supabase.co/rest/v1/usuarios?email=eq.${{email}}`, {{
                            headers: {{ "apikey": "{SUPABASE_KEY}" }}
                        }});
                        let data = await res.json();
                        if(data.length > 0) {{ document.getElementById('creditos').innerText = data[0].creditos + " disponibles"; }} 
                        else {{ document.getElementById('creditos').innerText = "Sin créditos. Pedile al admin."; }}
                    }} catch(e) {{ document.getElementById('creditos').innerText = "Error al cargar"; }}
                }}

                async function cerrarSesion() {{
                    await supabaseClient.auth.signOut();
                    location.reload();
                }}

                checkUser();
            </script>
        </body>
    </html>
    """


# --- FUNCIÓN DE TRANSCRIPCIÓN PARA AUDIOS LARGOS ---
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
        
        # Cortar en 10 minutos (600 segundos)
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

        nombre_archivo_nube = f"{uuid.uuid4()}_{audio.filename}"
        # Aseguramos que el navegador sepa que es un audio
        content_type = audio.content_type if audio.content_type and audio.content_type.startswith('audio') else 'audio/mpeg'
        s3_client.put_object(Bucket=BUCKET_NAME, Key=nombre_archivo_nube, Body=audio_bytes, ContentType=content_type)
        url_audio = f"{R2_PUBLIC_URL}/{nombre_archivo_nube}"
        
        supabase.table("transcripciones").insert({
            "user_email": email,
            "titulo": audio.filename,
            "texto": texto_plano,
            "audio_url": url_audio
        }).execute()
    except Exception as e:
        return f"Error procesando el audio: {e}"

    nuevos_creditos = creditos - 1
    supabase.table("usuarios").update({"creditos": nuevos_creditos}).eq("email", email).execute()

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


# --- HISTORIAL DE TRANSCRIPCIONES ---
@app.get("/historial", response_class=HTMLResponse)
async def ver_historial(email: str):
    response = supabase.table("transcripciones").select("id, titulo, texto, fecha, audio_url").eq("user_email", email).order("fecha", desc=True).execute()
    notas = response.data
    
    lista_html = ""
    for nota in notas:
        audio_url = nota.get('audio_url', '')
        reproductor = f"<audio id='audio-{nota['id']}' controls src='{audio_url}' style='width:100%; margin-bottom:15px;'></audio>" if audio_url else ""
        
        texto_html_historial = ""
        for linea in nota['texto'].split('\n'):
            if linea.startswith('['):
                partes = linea.split(']', 1)
                minuto_str = partes[0].replace('[', '')
                mins, segs = map(int, minuto_str.split(':'))
                segundos_totales = mins * 60 + segs
                texto_html_historial += f"<span class='minuto' onclick='saltarAHistorial({segundos_totales}, {nota['id']})'>[{minuto_str}]</span>{partes[1]}<br>"
            else:
                texto_html_historial += f"{linea}<br>"

        lista_html += f"""
        <div class='card'>
            <h3>📄 {nota['titulo']}</h3>
            {reproductor}
            <div class='texto-box'>{texto_html_historial}</div>
            <div class='fecha'>Guardado el: {nota['fecha']}</div>
        </div>
        """
        
    if not notas: 
        lista_html = "<p style='text-align:center; color:#666;'>Aún no tenés transcripciones guardadas.</p>"

    return f"""
    <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Mis Transcripciones</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f0f2f5; margin: 0; padding: 20px; color: #1a1a1a; }}
                .container {{ max-width: 600px; margin: 20px auto; }}
                h1 {{ text-align: center; color: #333; }}
                .btn {{ display: block; width: 100%; padding: 16px; font-size: 17px; border: none; border-radius: 12px; cursor: pointer; font-weight: 600; margin-bottom: 20px; text-decoration: none; box-sizing: border-box; text-align: center; }}
                .btn-primary {{ background: #007bff; color: white; }}
                .card {{ background: white; border-radius: 16px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
                h3 {{ margin-top: 0; color: #333; font-size: 20px; border-bottom: 2px solid #f0f0f0; padding-bottom: 10px; }}
                audio {{ width: 100%; margin-bottom: 15px; }}
                .texto-box {{ max-height: 300px; overflow-y: auto; background: #fafafa; border: 1px solid #eee; padding: 15px; border-radius: 8px; font-size: 15px; line-height: 1.6; color: #555; }}
                .fecha {{ font-size: 12px; color: #999; margin-top: 10px; text-align: right; }}
                .minuto {{ color: #007bff; cursor: pointer; font-weight: bold; background: #e7f1ff; padding: 3px 8px; border-radius: 6px; margin-right: 5px; display: inline-block; margin-bottom: 5px; font-size: 14px; }}
                .minuto:hover {{ background: #007bff; color: white; }}
            </style>
        </head>
        <body>
            <div class="container">
                <a href="/" class="btn btn-primary">⬅️ Volver a transcribir</a>
                <h1>📚 Mi Historial</h1>
                {lista_html}
                <script>
                    function saltarAHistorial(segundos, id) {{
                        const audio = document.getElementById('audio-' + id);
                        audio.currentTime = segundos;
                        audio.play();
                    }}
                </script>
            </div>
        </body>
    </html>
    """


# --- PANEL DE ADMINISTRACIÓN ---
@app.get("/admin-secreto", response_class=HTMLResponse)
async def panel_admin():
    response = supabase.table("usuarios").select("*").execute()
    usuarios = response.data
    
    tabla_html = ""
    for u in usuarios:
        tabla_html += f"<tr><td>{u['email']}</td><td>{u['creditos']}</td><td><form action='/agregar-creditos' method='post'><input type='hidden' name='email' value='{u['email']}'><input type='number' name='cantidad' value='5' style='width:60px; padding:5px;'><button type='submit' style='padding:5px 10px; background:green; color:white; border:none; border-radius:3px; cursor:pointer;'>Sumar</button></form></td></tr>"

    return f"""
    <html>
        <head><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Admin</title>
        <style>
            body {{ font-family: Arial; padding: 20px; background: #e9ecef; }}
            .contenedor {{ max-width: 800px; margin: auto; background: white; padding: 20px; border-radius: 8px; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
        </style>
        </head>
        <body>
            <div class="contenedor">
                <h1>Panel de Administración 🛠️</h1>
                <table>
                    <tr><th>Email</th><th>Créditos Actuales</th><th>Sumar Créditos</th></tr>
                    {tabla_html}
                </table>
                <br>
                <h3>Registrar nuevo usuario:</h3>
                <form action='/agregar-creditos' method='post'>
                    Email: <input type='email' name='email' required style='padding:8px;'>
                    Créditos: <input type='number' name='cantidad' value='5' style='width:60px; padding:8px;'>
                    <button type='submit' style='padding:8px 15px; background:#007bff; color:white; border:none; border-radius:4px; cursor:pointer;'>Crear y Sumar</button>
                </form>
            </div>
        </body>
    </html>
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