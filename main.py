from dotenv import load_dotenv
load_dotenv() # Esto le dice a Python que lea el archivo .env

from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import HTMLResponse
from groq import Groq
from supabase import create_client, Client
import os

app = FastAPI()

# --- CONFIGURACIÓN DE SERVICIOS ---
# Groq
client_groq = Groq()

# Supabase
url_supabase: str = os.environ.get("SUPABASE_URL")
key_supabase: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url_supabase, key_supabase)

# --- PÁGINA PRINCIPAL ---
@app.get("/", response_class=HTMLResponse)
async def leer_inicio():
    return """
    <html>
        <head>
            <title>Transcriptor Facu</title>
            <style>
                body { font-family: Arial; max-width: 500px; margin: 40px auto; text-align: center; background-color: #ffffff; color: #333;}
                input, button { margin: 10px; padding: 12px; width: 80%; box-sizing: border-box; border-radius: 5px; border: 1px solid #ccc;}
                button { background: #007bff; color: white; border: none; cursor: pointer;}
            </style>
        </head>
        <body>
            <h1>🎙️ Transcriptor Facu</h1>
            <form action="/transcribir" method="post" enctype="multipart/form-data">
                <input type="email" name="email" placeholder="Tu email" required><br>
                <input type="file" name="audio" accept="audio/*" required><br>
                <button type="submit">Transcribir (Gasta 1 crédito)</button>
            </form>
        </body>
    </html>
    """

# --- FUNCIÓN DE TRANSCRIPCIÓN ---
@app.post("/transcribir", response_class=HTMLResponse)
async def transcribir_audio(email: str = Form(...), audio: UploadFile = File(...)):
    # 1. Buscar usuario en Supabase
    response_db = supabase.table("usuarios").select("creditos").eq("email", email).execute()
    
    if not response_db.data:
        return "<h3>No estás registrado. Pedile créditos al administrador.</h3><a href='/'>Volver</a>"
    
    creditos = response_db.data[0]['creditos']

    if creditos <= 0:
        return f"<h3>No tenés créditos, {email}.</h3><a href='/'>Volver</a>"

    # 2. Transcribir
    audio_bytes = await audio.read()
    try:
        with open("temp_audio.wav", "wb") as f:
            f.write(audio_bytes)
        with open("temp_audio.wav", "rb") as audio_file:
            response_groq = client_groq.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=audio_file,
                response_format="text"
            )
    except Exception as e:
        return f"Error al transcribir: {e}"

    # 3. Descontar crédito en Supabase
    nuevos_creditos = creditos - 1
    supabase.table("usuarios").update({"creditos": nuevos_creditos}).eq("email", email).execute()

    # 4. Devolver HTML bonito
    return f"""
    <html>
        <head>
            <title>Resultado</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 40px auto; background-color: #ffffff; color: #333; }}
                .caja {{ background: #f4f7f6; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
                .texto {{ white-space: pre-wrap; font-size: 18px; line-height: 1.6; }}
                .creditos {{ color: #888; font-size: 14px; margin-top: 20px; border-top: 1px solid #eee; padding-top: 10px;}}
                button {{ background: #007bff; color: white; border: none; padding: 10px 15px; border-radius: 4px; cursor: pointer; text-decoration: none;}}
            </style>
        </head>
        <body>
            <div class="caja">
                <h3>📝 Transcripción:</h3>
                <div class="texto">{response_groq}</div>
                <div class="creditos">Te quedan <b>{nuevos_creditos}</b> créditos.</div>
                <br>
                <a href="/"><button>⬅️ Volver y transcribir otro</button></a>
            </div>
        </body>
    </html>
    """

# --- PANEL DE ADMINISTRACIÓN SECRETO ---
@app.get("/admin-secreto", response_class=HTMLResponse)
async def panel_admin():
    # Obtener todos los usuarios
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
    # Fijarse si el usuario ya existe
    res = supabase.table("usuarios").select("creditos").eq("email", email).execute()
    if res.data:
        # Si existe, le suma los créditos
        creditos_actuales = res.data[0]['creditos']
        nuevos = creditos_actuales + cantidad
        supabase.table("usuarios").update({"creditos": nuevos}).eq("email", email).execute()
    else:
        # Si no existe, lo crea con esos créditos
        supabase.table("usuarios").insert({"email": email, "creditos": cantidad}).execute()
    
    return "<h3>¡Créditos actualizados! Volvé al panel.</h3><a href='/admin-secreto'>Volver al panel</a>"