from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import HTMLResponse
from groq import Groq
from supabase import create_client, Client
import boto3
import os
import uuid

app = FastAPI()

# Configuración de servicios
client_groq = Groq()

# Supabase
SUPABASE_URL = "https://tfjhtxentxhufvdckkin.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRmamh0eGVudHhodWZ2ZGNra2luIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU1NDYwODQsImV4cCI6MjEwMTEyMjA4NH0.CoFiYtDfDGFtsCTk7R2CUQk7GL1DHItGhRIkBsEoyKA"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Cloudflare R2 (Tu nube de 10GB)
s3_client = boto3.client('s3',
    endpoint_url='https://6b630abe0d5b78c44a70c4a720a0c045.r2.cloudflarestorage.com', # Ej: https://xxxx.r2.cloudflarestorage.com
    aws_access_key_id='73a426845dd0aedde8c24fd59c2f9bd2',
    aws_secret_access_key='71b9deb00f0ab26a7162d1d3ff4f2b3ab916838705d251a0e37c44ce29e276e8',
    region_name='auto'
)
BUCKET_NAME = 'transcriptor-audios'

# --- PÁGINA PRINCIPAL ---
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

# --- FUNCIÓN DE TRANSCRIPCIÓN CON SUBIDA DE AUDIO ---
@app.post("/transcribir", response_class=HTMLResponse)
async def transcribir_audio(email: str = Form(...), audio: UploadFile = File(...)):
    response_db = supabase.table("usuarios").select("creditos").eq("email", email).execute()
    if not response_db.data: return "<h3>No estás registrado.</h3><a href='/'>Volver</a>"
    creditos = response_db.data[0]['creditos']
    if creditos <= 0: return f"<h3>No tenés créditos, {email}.</h3><a href='/'>Volver</a>"

    audio_bytes = await audio.read()
    try:
        # 1. Transcribir con Groq
        with open("temp_audio.wav", "wb") as f: f.write(audio_bytes)
        with open("temp_audio.wav", "rb") as audio_file:
            response_groq = client_groq.audio.transcriptions.create(model="whisper-large-v3-turbo", file=audio_file, response_format="text")
        
        # 2. Subir el audio a Cloudflare R2
        nombre_archivo_nube = f"{uuid.uuid4()}_{audio.filename}"
        s3_client.put_object(Bucket=BUCKET_NAME, Key=nombre_archivo_nube, Body=audio_bytes, ContentType=audio.content_type)
        url_audio = f"https://pub-af8d124ed9bc47f19c25885232899998.r2.dev/{nombre_archivo_nube}" # OJO: Reemplazar pub-xxxxx por tu link público de R2
        
        # 3. Guardar en el historial con la URL del audio
        supabase.table("transcripciones").insert({
            "user_email": email,
            "titulo": audio.filename,
            "texto": response_groq,
            "audio_url": url_audio
        }).execute()
    except Exception as e:
        return f"Error: {e}"

    nuevos_creditos = creditos - 1
    supabase.table("usuarios").update({"creditos": nuevos_creditos}).eq("email", email).execute()

    return f"""
    <html>
        <head><title>Resultado</title>
        <style>
            body {{ font-family: Arial; max-width: 600px; margin: 40px auto; background-color: #f8f9fa; color: #333; }}
            .caja {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .texto {{ white-space: pre-wrap; font-size: 18px; line-height: 1.6; }}
            .creditos {{ color: #888; font-size: 14px; margin-top: 20px; border-top: 1px solid #eee; padding-top: 10px;}}
            button {{ background: #007bff; color: white; border: none; padding: 10px 15px; border-radius: 4px; cursor: pointer; text-decoration: none;}}
            audio {{ width: 100%; margin-bottom: 20px; }}
        </style>
        </head>
        <body>
            <div class="caja">
                <h3>📝 Transcripción:</h3>
                <!-- Reproductor de audio mágico -->
                <audio controls src="{url_audio}"></audio>
                <div class="texto">{response_groq}</div>
                <div class="creditos">Te quedan <b>{nuevos_creditos}</b> créditos.</div>
                <br>
                <a href="/historial?email={email}"><button>📚 Ver mi historial</button></a>
            </div>
        </body>
    </html>
    """

# --- HISTORIAL CON REPRODUCTOR ---
@app.get("/historial", response_class=HTMLResponse)
async def ver_historial(email: str):
    # Tuve que agregar el audio_url en el select
    response = supabase.table("transcripciones").select("titulo, texto, fecha, audio_url").eq("user_email", email).order("fecha", desc=True).execute()
    notas = response.data
    
    lista_html = ""
    for nota in notas:
        audio_url = nota.get('audio_url', '')
        reproductor = f"<audio controls src='{audio_url}' style='width:100%; margin-bottom:10px;'></audio>" if audio_url else ""
        lista_html += f"""
        <div style='background:white; padding:15px; margin-bottom:15px; border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,0.1);'>
            <h3 style='margin-top:0; color:#333;'>📄 {nota['titulo']}</h3>
            {reproductor}
            <div style='white-space: pre-wrap; font-size:14px; color:#555; max-height:200px; overflow-y:auto; border:1px solid #eee; padding:10px; border-radius:5px;'>{nota['texto']}</div>
            <p style='font-size:12px; color:#888; margin-bottom:0; margin-top:10px;'>Guardado el: {nota['fecha']}</p>
        </div>
        """
        
    if not notas: lista_html = "<p>Aún no tenés transcripciones guardadas.</p>"

    return f"""
    <html>
        <head><title>Mis Transcripciones</title>
        <style>
            body {{ font-family: Arial; max-width: 600px; margin: 20px auto; background-color: #f8f9fa; color: #333; }}
            button {{ background: #007bff; color: white; border: none; padding: 10px 15px; border-radius: 4px; cursor: pointer; text-decoration:none; margin-bottom: 20px;}}
        </style>
        </head>
        <body>
            <a href="/"><button>⬅️ Volver a transcribir</button></a>
            <h1>📚 Mi Historial</h1>
            {lista_html}
        </body>
    </html>
    """

# --- PANEL DE ADMIN (Igual que antes) ---
@app.get("/admin-secreto", response_class=HTMLResponse)
async def panel_admin():
    response = supabase.table("usuarios").select("*").execute()
    usuarios = response.data
    tabla_html = ""
    for u in usuarios:
        tabla_html += f"<tr><td>{u['email']}</td><td>{u['creditos']}</td><td><form action='/agregar-creditos' method='post'><input type='hidden' name='email' value='{u['email']}'><input type='number' name='cantidad' value='5' style='width:60px; padding:5px;'><button type='submit' style='padding:5px 10px; background:green; color:white; border:none; border-radius:3px; cursor:pointer;'>Sumar</button></form></td></tr>"

    return f"""
    <html><head><title>Admin</title><style>body {{ font-family: Arial; padding: 20px; background: #e9ecef; }} .contenedor {{ max-width: 800px; margin: auto; background: white; padding: 20px; border-radius: 8px; }} table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }} th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }} th {{ background-color: #f2f2f2; }}</style></head>
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