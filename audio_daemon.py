#!/usr/bin/env python3
"""
Audio Daemon - Script independiente para grabacion y transcripcion.
Hotkeys propios (no depende de hotkey_notifier_wayland.py):
  A+1  ->  inicia grabacion del audio del sistema
  S+1  ->  detiene grabacion, transcribe con Whisper y guarda .txt

Uso:
    sudo python3 audio_daemon.py
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
    Corre parecord como pablo con su entorno completo de PipeWire.
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

        env = {
            "HOME":                     f"/home/{USUARIO}",
            "USER":                     USUARIO,
            "XDG_RUNTIME_DIR":          f"/run/user/{uid}",
            "PULSE_SERVER":             f"unix:/run/user/{uid}/pulse/native",
            "DBUS_SESSION_BUS_ADDRESS": dbus,
            "PATH":                     "/usr/bin:/bin:/usr/local/bin",
        }

        print(f"[🎙] Grabando audio del sistema...")
        print(f"     Archivo: {_archivo_audio_actual}")
        print(f"     Presiona S+1 para detener y transcribir.")

        # Correr parecord directamente sin sudo
        _proceso_grabacion = subprocess.Popen(
            [
                "parecord",
                f"--device={AUDIO_MONITOR}",
                "--file-format=wav",
                _archivo_audio_actual,
            ],
            stdout=subprocess.DEVNULL,
            stderr=None,  # mostrar errores en terminal
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

    threading.Thread(target=_transcribir_audio, args=(archivo_audio,), daemon=True).start()


def _transcribir_audio(archivo_audio):
    """Envia el .wav a Whisper y guarda la transcripcion en .txt."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("[X] OPENAI_API_KEY no encontrada en .env")
        return

    print("[Whisper] Transcribiendo...")

    try:
        with open(archivo_audio, "rb") as f:
            audio_data = f.read()

        boundary = "----FormBoundary7MA4YWxkTrZu0gW"
        body  = b""
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="model"\r\n\r\n'
        body += b"whisper-1\r\n"
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(archivo_audio)}"\r\n'.encode()
        body += b"Content-Type: audio/wav\r\n\r\n"
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

        with urllib.request.urlopen(req, timeout=60) as response:
            data          = json.loads(response.read().decode("utf-8"))
            transcripcion = data.get("text", "").strip()

        if not transcripcion:
            print("[!] Transcripcion vacia.")
            return

        nombre_txt = archivo_audio.replace(".wav", ".txt")
        with open(nombre_txt, "w", encoding="utf-8") as f:
            f.write(transcripcion)

        print(f"[OK] Transcripcion guardada: {nombre_txt}")
        print(f"     Preview: {transcripcion[:200]}")

        os.remove(archivo_audio)
        print("[OK] Audio temporal eliminado.")

    except urllib.error.HTTPError as e:
        print(f"[X] Error HTTP {e.code}: {e.read().decode()}")
    except Exception as e:
        print(f"[X] Error: {e}")


def encontrar_teclado():
    """Usa el mismo teclado identificado: /dev/input/event2."""
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
    Detecta A+1 para grabar y S+1 para detener y transcribir.
    Completamente independiente de hotkey_notifier_wayland.py.
    """
    cargar_env()

    dev = encontrar_teclado()
    if not dev:
        sys.exit(1)

    os.makedirs(CARPETA_TRANSCRIPCIONES, exist_ok=True)

    print("=" * 55)
    print(f"  Teclado      : {dev.name}")
    print(f"  Transcripciones: {CARPETA_TRANSCRIPCIONES}")
    print(f"  A+1  ->  iniciar grabacion")
    print(f"  S+1  ->  detener y transcribir")
    print(f"  Salir: Ctrl+C")
    print("=" * 55)

    a_activo = False
    s_activo = False

    try:
        for evento in dev.read_loop():
            if evento.type != ecodes.EV_KEY:
                continue

            key_event = evdev.categorize(evento)

            if key_event.scancode == KEY_A:
                a_activo = (key_event.keystate != 0)

            if key_event.scancode == KEY_S:
                s_activo = (key_event.keystate != 0)

            # A+1 -> iniciar grabacion
            if (key_event.scancode == KEY_1
                    and key_event.keystate == 1
                    and a_activo):
                print("[Hotkey] A+1 -> iniciar grabacion")
                threading.Thread(target=iniciar_grabacion, daemon=True).start()

            # S+1 -> detener y transcribir
            if (key_event.scancode == KEY_1
                    and key_event.keystate == 1
                    and s_activo):
                print("[Hotkey] S+1 -> detener y transcribir")
                threading.Thread(target=detener_y_transcribir, daemon=True).start()

    except KeyboardInterrupt:
        if _proceso_grabacion:
            _proceso_grabacion.terminate()
        print("\n[!] Audio Daemon detenido.")
    except PermissionError:
        print("\n[X] Ejecuta con: sudo python3 audio_daemon.py")


if __name__ == "__main__":
    main()