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

# Supabase (Base de datos)
SUPABASE_URL = "https://tfjhtxentxhufvdckkin.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRmamh0eGVudHhodWZ2ZGNra2luIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU1NDYwODQsImV4cCI6MjEwMTEyMjA4NH0.CoFiYtDfDGFtsCTk7R2CUQk7GL1DHItGhRIkBsEoyKA"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Cloudflare R2 (Nube de audios)
s3_client = boto3.client('s3',
    endpoint_url='https://6b630abe0d5b78c44a70c4a720a0c045.r2.cloudflarestorage.com', 
    aws_access_key_id='73a426845dd0aedde8c24fd59c2f9bd2',
    aws_secret_access_key='71b9deb00f0ab26a7162d1d3ff4f2b3ab916838705d251a0e37c44ce29e276e8',
    region_name='auto'
)
BUCKET_NAME = 'transcriptor-audios'
R2_PUBLIC_URL = 'https://pub-af8d124ed9bc47f19c25885232899998.r2.dev' 




# --- PÁGINA PRINCIPAL CON LOGIN DE GOOGLE ---
@app.get("/", response_class=HTMLResponse)
async def leer_inicio():
    return f"""
    <html>
        <head>
            <title>Transcriptor Facu</title>
            <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
            <style>
                body {{ font-family: Arial; max-width: 500px; margin: 40px auto; text-align: center; background-color: #f8f9fa; color: #333;}}
                .caja {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); margin-top: 20px; }}
                button {{ background: #007bff; color: white; border: none; padding: 12px 20px; border-radius: 5px; cursor: pointer; width: 100%; margin-top: 10px;}}
                .google-btn {{ background: #db4437; }}
                input[type="file"] {{ width: 80%; padding: 10px; margin: 10px auto; border-radius: 5px; border: 1px solid #ccc; }}
                input[type="hidden"] {{ display: none; }}
            </style>
        </head>
        <body>
            <div class="caja">
                <h1>🎙️ Transcriptor Facu</h1>
                
                <div id="login-box">
                    <p>Ingresá para empezar a transcribir tus clases</p>
                    <button class="google-btn" onclick="loginConGoogle()">Iniciar sesión con Google</button>
                </div>

                <div id="app-box" style="display: none;">
                    <p>Hola, <b id="user-email"></b> 👋</p>
                    <p>Créditos disponibles: <b id="creditos">Cargando...</b></p>
                    <form action="/transcribir" method="post" enctype="multipart/form-data">
                        <input type="hidden" name="email" id="hidden-email">
                        <input type="file" name="audio" accept="audio/*" required><br>
                        <button type="submit">Transcribir (Gasta 1 crédito)</button>
                    </form>
                    <a id="historial-link" href="#" style="display:block; margin-top: 15px;"><button style="background: #28a745;">📚 Ver mi historial</button></a>
                    <button onclick="cerrarSesion()" style="background: #6c757d; margin-top: 20px;">Cerrar sesión</button>
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
                        if(data.length > 0) {{ document.getElementById('creditos').innerText = data[0].creditos; }} 
                        else {{ document.getElementById('creditos').innerText = "No tienes créditos. Pide al admin."; }}
                    }} catch(e) {{ document.getElementById('creditos').innerText = "Error al cargar créditos"; }}
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


# --- FUNCIÓN DE TRANSCRIPCIÓN PARA AUDIOS LARGOS (Con ffmpeg directo) ---
@app.post("/transcribir", response_class=HTMLResponse)
async def transcribir_audio(email: str = Form(...), audio: UploadFile = File(...)):
    # 1. Verificar créditos
    response_db = supabase.table("usuarios").select("creditos").eq("email", email).execute()
    if not response_db.data:
        return "<h3>No estás registrado.</h3><a href='/'>Volver</a>"
    
    creditos = response_db.data[0]['creditos']
    if creditos <= 0:
        return f"<h3>No tenés créditos, {email}.</h3><a href='/'>Volver</a>"

    audio_bytes = await audio.read()
    try:
        # 2. Guardar el audio original temporalmente
        extension = audio.filename.split('.')[-1].lower()
        temp_original = f"temp_original.{extension}"
        with open(temp_original, "wb") as f: f.write(audio_bytes)
        
        # 3. Cortar el audio con ffmpeg en pedazos de 20 minutos (1200 segundos)
        # Esto lo convierte a WAV 16kHz mono, que es lo mejor para la IA
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run([
            ffmpeg_exe, "-i", temp_original, 
            "-f", "segment", "-segment_time", "600", 
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", 
            "temp_chunk_%03d.wav"
        ], check=True, capture_output=True)
        
        # 4. Buscar todos los pedacitos que se crearon
        chunks = sorted(glob.glob("temp_chunk_*.wav"))
        
        texto_plano = ""
        texto_html = ""
        
        # 5. Mandar cada pedacito a Groq
        for i, chunk_filename in enumerate(chunks):
            with open(chunk_filename, "rb") as audio_file:
                response_groq = client_groq.audio.transcriptions.create(
                    model="whisper-large-v3-turbo", 
                    file=audio_file, 
                    response_format="verbose_json"
                )
            
            # 6. Ajustar los minutos (Sumamos 20 minutos por cada pedazo que pasó)
            offset_segundos = i * 600.0
            for segmento in response_groq.segments:
                inicio_real = segmento['start'] + offset_segundos
                minutos = int(inicio_real // 60)
                segundos = int(inicio_real % 60)
                
                texto_plano += f"[{minutos:02d}:{segundos:02d}] {segmento['text']}\n"
                texto_html += f"<span class='minuto' onclick='saltarA({inicio_real})'>[{minutos:02d}:{segundos:02d}]</span> {segmento['text']}<br>"
            
            # Borramos el pedacito para no llenar el disco
            os.remove(chunk_filename)
        
        # Borramos el original temporal
        if os.path.exists(temp_original): os.remove(temp_original)

        # 7. Subir el audio COMPLETO original a Cloudflare R2
        nombre_archivo_nube = f"{uuid.uuid4()}_{audio.filename}"
        s3_client.put_object(Bucket=BUCKET_NAME, Key=nombre_archivo_nube, Body=audio_bytes, ContentType=audio.content_type)
        url_audio = f"{R2_PUBLIC_URL}/{nombre_archivo_nube}"
        
        # 8. Guardar en el historial
        supabase.table("transcripciones").insert({
            "user_email": email,
            "titulo": audio.filename,
            "texto": texto_plano,
            "audio_url": url_audio
        }).execute()
    except Exception as e:
        return f"Error procesando el audio: {e}"

    # 9. Descontar crédito
    nuevos_creditos = creditos - 1
    supabase.table("usuarios").update({"creditos": nuevos_creditos}).eq("email", email).execute()

    # 10. Mostrar el resultado
    return f"""
    <html>
        <head><title>Resultado</title>
        <style>
            body {{ font-family: Arial; max-width: 600px; margin: 40px auto; background-color: #f8f9fa; color: #333; }}
            .caja {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .texto {{ white-space: pre-wrap; font-size: 18px; line-height: 1.8; }}
            .creditos {{ color: #888; font-size: 14px; margin-top: 20px; border-top: 1px solid #eee; padding-top: 10px;}}
            button {{ background: #007bff; color: white; border: none; padding: 10px 15px; border-radius: 4px; cursor: pointer; text-decoration: none;}}
            .minuto {{ color: #007bff; cursor: pointer; font-weight: bold; background: #e7f1ff; padding: 2px 6px; border-radius: 4px; margin-right: 5px; }}
            .minuto:hover {{ background: #007bff; color: white; }}
        </style>
        </head>
        <body>
            <div class="caja">
                <h3>📝 Transcripción:</h3>
                <audio id="reproductor" controls src="{url_audio}" style="width: 100%; margin-bottom: 20px;"></audio>
                <div class="texto">{texto_html}</div>
                <div class="creditos">Te quedan <b>{nuevos_creditos}</b> créditos.</div>
                <br>
                <a href="/historial?email={email}"><button>📚 Ver mi historial</button></a>
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
    # Buscar las transcripciones del usuario
    response = supabase.table("transcripciones").select("id, titulo, texto, fecha, audio_url").eq("user_email", email).order("fecha", desc=True).execute()
    notas = response.data
    
    lista_html = ""
    for nota in notas:
        audio_url = nota.get('audio_url', '')
        # El reproductor de audio
        reproductor = f"<audio id='audio-{nota['id']}' controls src='{audio_url}' style='width:100%; margin-bottom:10px;'></audio>" if audio_url else ""
        
        # El texto (lo convertimos para que los minutitos sean clickeables en el historial también)
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
        <div style='background:white; padding:15px; margin-bottom:15px; border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,0.1);'>
            <h3 style='margin-top:0; color:#333;'>📄 {nota['titulo']}</h3>
            {reproductor}
            <div style='font-size:14px; color:#555; max-height:200px; overflow-y:auto; border:1px solid #eee; padding:10px; border-radius:5px;'>{texto_html_historial}</div>
            <p style='font-size:12px; color:#888; margin-bottom:0; margin-top:10px;'>Guardado el: {nota['fecha']}</p>
        </div>
        """
        
    if not notas: 
        lista_html = "<p>Aún no tenés transcripciones guardadas.</p>"

    return f"""
    <html>
        <head>
            <title>Mis Transcripciones</title>
            <style>
                body {{ font-family: Arial; max-width: 600px; margin: 20px auto; background-color: #f8f9fa; color: #333; }}
                button {{ background: #007bff; color: white; border: none; padding: 10px 15px; border-radius: 4px; cursor: pointer; text-decoration:none; margin-bottom: 20px;}}
                .minuto {{ color: #007bff; cursor: pointer; font-weight: bold; background: #e7f1ff; padding: 2px 6px; border-radius: 4px; margin-right: 5px; }}
                .minuto:hover {{ background: #007bff; color: white; }}
            </style>
        </head>
        <body>
            <a href="/"><button>⬅️ Volver a transcribir</button></a>
            <h1>📚 Mi Historial</h1>
            {lista_html}
            <script>
                function saltarAHistorial(segundos, id) {{
                    const audio = document.getElementById('audio-' + id);
                    audio.currentTime = segundos;
                    audio.play();
                }}
            </script>
        </body>
    </html>
    """


# --- PANEL DE ADMINISTRACIÓN SECRETO ---
@app.get("/admin-secreto", response_class=HTMLResponse)
async def panel_admin():
    response = supabase.table("usuarios").select("*").execute()
    usuarios = response.data
    
    tabla_html = ""
    for u in usuarios:
        tabla_html += f"<tr><td>{u['email']}</td><td>{u['creditos']}</td><td><form action='/agregar-creditos' method='post'><input type='hidden' name='email' value='{u['email']}'><input type='number' name='cantidad' value='5' style='width:60px; padding:5px;'><button type='submit' style='padding:5px 10px; background:green; color:white; border:none; border-radius:3px; cursor:pointer;'>Sumar</button></form></td></tr>"

    return f"""
    <html>
        <head><title>Admin</title>
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