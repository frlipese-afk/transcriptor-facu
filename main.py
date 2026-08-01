from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import HTMLResponse
from groq import Groq
import os

app = FastAPI()

client = Groq() 

usuarios_db = {
    "mama@gmail.com": {"creditos": 5},
    "amigo1@gmail.com": {"creditos": 3},
    "invitado@gmail.com": {"creditos": 1}
}


@app.get("/", response_class=HTMLResponse)
async def leer_inicio():
    return """
    <html>
        <head>
            <title>Transcriptor Facu</title>
            <style>
                body { font-family: Arial; max-width: 500px; margin: 40px auto; text-align: center; }
                input, button { margin: 10px; padding: 10px; }
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


@app.post("/transcribir", response_class=HTMLResponse)
async def transcribir_audio(email: str = Form(...), audio: UploadFile = File(...)):
    
    if email not in usuarios_db:
        return {"error": "No estás registrado. Pedile créditos al admin."}
    
    if usuarios_db[email]["creditos"] <= 0:
        return {"error": "No tenés créditos. Pasá a buscar más!"}

    
    audio_bytes = await audio.read()
    
    
    try:
        
        with open("temp_audio.wav", "wb") as f:
            f.write(audio_bytes)
            
        
        with open("temp_audio.wav", "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=audio_file,
                response_format="text"
            )
    except Exception as e:
        return {"error": f"Error al transcribir: {e}"}

    
    usuarios_db[email]["creditos"] -= 1

        
    return f"""
    <html>
        <head>
            <title>Resultado</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 40px auto; background-color: #f4f7f6; }}
                .caja {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
                .texto {{ white-space: pre-wrap; font-size: 18px; line-height: 1.6; color: #333; }}
                .creditos {{ color: #888; font-size: 14px; margin-top: 20px; border-top: 1px solid #eee; padding-top: 10px;}}
                button {{ background: #007bff; color: white; border: none; padding: 10px 15px; border-radius: 4px; cursor: pointer; text-decoration: none;}}
            </style>
        </head>
        <body>
            <div class="caja">
                <h3>📝 Transcripción:</h3>
                <div class="texto">{response}</div>
                
                <div class="creditos">Te quedan <b>{usuarios_db[email]["creditos"]}</b> créditos.</div>
                
                <br>
                <a href="/"><button>⬅️ Volver y transcribir otro</button></a>
            </div>
        </body>
    </html>
    """