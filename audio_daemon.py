#!/usr/bin/env python3
"""
Audio Daemon - Script independiente para grabacion y transcripcion.
Hotkeys:
  A+1  ->  inicia grabacion del audio del sistema
  S+1  ->  detiene grabacion, transcribe con Whisper y guarda .txt
  G+1  ->  abre selector de archivos, extrae audio del video y transcribe en ingles

Uso:
    XDG_RUNTIME_DIR=/run/user/1001 PULSE_SERVER=unix:/run/user/1001/pulse/native python3 audio_daemon.py
"""

import os
import sys
import time
import threading
import subprocess
import json
import urllib.request
import urllib.error
from datetime import datetime
import evdev
from evdev import ecodes

# ── Configuracion ──────────────────────────────────────────────────────────────
USUARIO                 = "pablo"
CARPETA_TRANSCRIPCIONES = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "transcripciones"
)
AUDIO_MONITOR   = "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"
WHISPER_API_URL = "https://api.openai.com/v1/audio/transcriptions"

# Teclas
KEY_A = ecodes.KEY_A
KEY_S = ecodes.KEY_S
KEY_G = ecodes.KEY_G
KEY_1 = ecodes.KEY_1
# ──────────────────────────────────────────────────────────────────────────────

# Estado global de grabacion
_proceso_grabacion    = None
_archivo_audio_actual = None
_lock = threading.Lock()


def cargar_env():
    """Lee el .env y carga las variables de entorno."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        print(f"[X] Archivo .env no encontrado: {env_path}")
        sys.exit(1)
    with open(env_path) as f:
        for linea in f:
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                clave, valor = linea.split("=", 1)
                os.environ[clave.strip()] = valor.strip()
    print("[OK] .env cargado.")


def obtener_uid_dbus():
    """Obtiene uid y dbus del usuario real."""
    uid  = subprocess.check_output(["id", "-u", USUARIO]).decode().strip()
    dbus = f"unix:path=/run/user/{uid}/bus"
    return uid, dbus


def iniciar_grabacion():
    """
    Inicia parecord capturando el monitor del sink principal.
    Corre parecord con el entorno completo de PipeWire.
    """
    global _proceso_grabacion, _archivo_audio_actual

    with _lock:
        if _proceso_grabacion is not None:
            print("[!] Ya hay una grabacion activa. Presiona S+1 para detenerla.")
            return

        os.makedirs(CARPETA_TRANSCRIPCIONES, exist_ok=True)

        timestamp             = datetime.now().strftime("%Y%m%d_%H%M%S")
        _archivo_audio_actual = os.path.join(
            CARPETA_TRANSCRIPCIONES, f"audio_{timestamp}.wav"
        )

        uid, dbus = obtener_uid_dbus()
        env_audio = os.environ.copy()
        env_audio["XDG_RUNTIME_DIR"]          = f"/run/user/{uid}"
        env_audio["PULSE_SERVER"]             = f"unix:/run/user/{uid}/pulse/native"
        env_audio["PULSE_RUNTIME_PATH"]       = f"/run/user/{uid}/pulse"
        env_audio["DBUS_SESSION_BUS_ADDRESS"] = dbus

        print(f"[Mic] Grabando audio del sistema...")
        print(f"      Archivo: {_archivo_audio_actual}")
        print(f"      Presiona S+1 para detener y transcribir.")

        _proceso_grabacion = subprocess.Popen(
            [
                "parecord",
                f"--device={AUDIO_MONITOR}",
                "--file-format=wav",
                _archivo_audio_actual,
            ],
            env=env_audio,
            stdout=subprocess.DEVNULL,
            stderr=None,
        )


def detener_y_transcribir():
    """Detiene parecord y lanza la transcripcion en un hilo separado."""
    global _proceso_grabacion, _archivo_audio_actual

    with _lock:
        if _proceso_grabacion is None:
            print("[!] No hay grabacion activa. Presiona A+1 para iniciar.")
            return

        _proceso_grabacion.terminate()
        _proceso_grabacion.wait()
        archivo_audio         = _archivo_audio_actual
        _proceso_grabacion    = None
        _archivo_audio_actual = None

    print(f"[OK] Grabacion detenida: {archivo_audio}")

    if not os.path.exists(archivo_audio):
        print(f"[X] Archivo no encontrado: {archivo_audio}")
        return

    tamanio = os.path.getsize(archivo_audio)
    print(f"[OK] Tamanio: {tamanio} bytes")

    if tamanio < 1000:
        print("[X] Audio vacio o muy corto.")
        os.remove(archivo_audio)
        return

    threading.Thread(target=_transcribir_audio, args=(archivo_audio, None), daemon=True).start()


def seleccionar_video_y_transcribir():
    """
    Abre un selector de archivos con zenity para elegir un video.
    Extrae el audio con ffmpeg y lo envia a Whisper forzando ingles.
    Guarda la transcripcion en transcripciones/.
    """
    uid, dbus = obtener_uid_dbus()

    print("[G+1] Abriendo selector de archivos...")

    # Abrir zenity para seleccionar video
    resultado = subprocess.run([
        "sudo", "-u", USUARIO,
        "env",
        "DISPLAY=:0",
        f"DBUS_SESSION_BUS_ADDRESS={dbus}",
        f"XDG_RUNTIME_DIR=/run/user/{uid}",
        "zenity",
        "--file-selection",
        "--title=Selecciona un video para transcribir",
        "--file-filter=Videos | *.mp4 *.mkv *.avi *.mov *.webm *.flv *.m4v",
    ], capture_output=True, text=True)

    ruta_video = resultado.stdout.strip()

    if not ruta_video or not os.path.exists(ruta_video):
        print("[!] No se selecciono ningun archivo o no existe.")
        return

    print(f"[OK] Video seleccionado: {ruta_video}")

    # Extraer audio del video con ffmpeg
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_tmp  = os.path.join(CARPETA_TRANSCRIPCIONES, f"video_audio_{timestamp}.mp3")

    print(f"[ffmpeg] Extrayendo audio del video...")
    resultado_ffmpeg = subprocess.run([
        "ffmpeg",
        "-i", ruta_video,       # archivo de entrada
        "-vn",                  # sin video
        "-acodec", "libmp3lame", # codec mp3
        "-ar", "16000",         # frecuencia 16khz (optima para Whisper)
        "-ac", "1",             # mono
        "-q:a", "2",            # calidad alta
        "-y",                   # sobreescribir si existe
        audio_tmp,
    ], capture_output=True, text=True)

    if resultado_ffmpeg.returncode != 0:
        print(f"[X] Error ffmpeg: {resultado_ffmpeg.stderr}")
        return

    if not os.path.exists(audio_tmp):
        print("[X] ffmpeg no creo el archivo de audio.")
        return

    tamanio = os.path.getsize(audio_tmp)
    print(f"[OK] Audio extraido: {audio_tmp} ({tamanio} bytes)")

    # Transcribir forzando ingles
    _transcribir_audio(audio_tmp, idioma="en")


def _transcribir_audio(archivo_audio, idioma=None):
    """
    Envia el archivo de audio a Whisper y guarda la transcripcion en .txt.
    Parametros:
      - archivo_audio: ruta al archivo .wav o .mp3
      - idioma: codigo de idioma para forzar (ej: 'en' para ingles, None para auto)
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("[X] OPENAI_API_KEY no encontrada en .env")
        return

    print(f"[Whisper] Transcribiendo{' en ingles' if idioma == 'en' else ''}...")

    try:
        with open(archivo_audio, "rb") as f:
            audio_data = f.read()

        # Detectar tipo de archivo
        ext = os.path.splitext(archivo_audio)[1].lower()
        mime = "audio/mpeg" if ext == ".mp3" else "audio/wav"

        boundary = "----FormBoundary7MA4YWxkTrZu0gW"
        body  = b""

        # campo model
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="model"\r\n\r\n'
        body += b"whisper-1\r\n"

        # campo language (forzar idioma si se especifica)
        if idioma:
            body += f"--{boundary}\r\n".encode()
            body += b'Content-Disposition: form-data; name="language"\r\n\r\n'
            body += f"{idioma}\r\n".encode()

        # campo file
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(archivo_audio)}"\r\n'.encode()
        body += f"Content-Type: {mime}\r\n\r\n".encode()
        body += audio_data
        body += b"\r\n"
        body += f"--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            WHISPER_API_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  f"multipart/form-data; boundary={boundary}",
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            data          = json.loads(response.read().decode("utf-8"))
            transcripcion = data.get("text", "").strip()

        if not transcripcion:
            print("[!] Transcripcion vacia.")
            return

        # Guardar .txt con mismo nombre base
        nombre_txt = os.path.splitext(archivo_audio)[0] + ".txt"
        with open(nombre_txt, "w", encoding="utf-8") as f:
            f.write(transcripcion)

        print(f"[OK] Transcripcion guardada: {nombre_txt}")
        print(f"     Preview: {transcripcion[:200]}")

        # Eliminar audio temporal
        os.remove(archivo_audio)
        print("[OK] Audio temporal eliminado.")

    except urllib.error.HTTPError as e:
        print(f"[X] Error HTTP {e.code}: {e.read().decode()}")
    except Exception as e:
        print(f"[X] Error: {e}")


def encontrar_teclado():
    """Usa el teclado identificado: /dev/input/event2."""
    try:
        dev = evdev.InputDevice("/dev/input/event2")
        print(f"[OK] Teclado: {dev.name} ({dev.path})")
        return dev
    except Exception as e:
        print(f"[X] No se pudo abrir el teclado: {e}")
        return None


def main():
    """
    Bucle principal independiente.
    Detecta A+1, S+1 y G+1.
    """
    cargar_env()

    dev = encontrar_teclado()
    if not dev:
        sys.exit(1)

    os.makedirs(CARPETA_TRANSCRIPCIONES, exist_ok=True)

    print("=" * 55)
    print(f"  Teclado        : {dev.name}")
    print(f"  Transcripciones: {CARPETA_TRANSCRIPCIONES}")
    print(f"  A+1  ->  iniciar grabacion de audio")
    print(f"  S+1  ->  detener y transcribir")
    print(f"  G+1  ->  seleccionar video y transcribir en ingles")
    print(f"  Salir: Ctrl+C")
    print("=" * 55)

    a_activo = False
    s_activo = False
    g_activo = False

    try:
        for evento in dev.read_loop():
            if evento.type != ecodes.EV_KEY:
                continue

            key_event = evdev.categorize(evento)

            if key_event.scancode == KEY_A:
                a_activo = (key_event.keystate != 0)
            if key_event.scancode == KEY_S:
                s_activo = (key_event.keystate != 0)
            if key_event.scancode == KEY_G:
                g_activo = (key_event.keystate != 0)

            if key_event.scancode == KEY_1 and key_event.keystate == 1:
                if a_activo:
                    print("[Hotkey] A+1 -> iniciar grabacion")
                    threading.Thread(target=iniciar_grabacion, daemon=True).start()
                elif s_activo:
                    print("[Hotkey] S+1 -> detener y transcribir")
                    threading.Thread(target=detener_y_transcribir, daemon=True).start()
                elif g_activo:
                    print("[Hotkey] G+1 -> seleccionar video y transcribir")
                    threading.Thread(target=seleccionar_video_y_transcribir, daemon=True).start()

    except KeyboardInterrupt:
        if _proceso_grabacion:
            _proceso_grabacion.terminate()
        print("\n[!] Audio Daemon detenido.")
    except PermissionError:
        print("\n[X] Ejecuta con los permisos correctos.")


if __name__ == "__main__":
    main()
