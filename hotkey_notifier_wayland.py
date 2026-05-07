#!/usr/bin/env python3
"""
Hotkey Notifier - Compatible con Wayland
Hotkeys:
  1+X  -> Captura simple + GPT-4o + ventana nueva cada vez
  3+X  -> Captura simple + GPT-4o + cierra ventana anterior y abre nueva
  5+X  -> Capturas con scroll + GPT-4o + ventana nueva

Uso:
    sudo python3 hotkey_notifier_wayland.py
"""

import sys
import os
import time
import threading
import subprocess
import json
import base64
import urllib.request
import urllib.error
from datetime import datetime
import evdev
from evdev import ecodes

# ── Cargar variables de entorno desde .env ─────────────────────────────────────
def cargar_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        print(f"[X] Archivo .env no encontrado en: {env_path}")
        sys.exit(1)
    with open(env_path) as f:
        for linea in f:
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                clave, valor = linea.split("=", 1)
                os.environ[clave.strip()] = valor.strip()
    print("[OK] Variables de entorno cargadas desde .env")

cargar_env()

# ── Configuracion ──────────────────────────────────────────────────────────────
TITULO           = "GPT-4o Responde"
CARPETA_CAPTURAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capturas")
USUARIO          = "pablo"
OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY")
OPENAI_API_URL   = "https://api.openai.com/v1/chat/completions"

if not OPENAI_API_KEY:
    print("[X] OPENAI_API_KEY no encontrada en el archivo .env")
    sys.exit(1)

# Codigos de teclas
KEY_X = ecodes.KEY_X
KEY_1 = ecodes.KEY_1
KEY_3 = ecodes.KEY_3
KEY_5 = ecodes.KEY_5

# Estado ventana permanente (3+X)
_ventana_proc = None
_ventana_lock = threading.Lock()


def obtener_uid_dbus():
    uid  = subprocess.check_output(["id", "-u", USUARIO]).decode().strip()
    dbus = f"unix:path=/run/user/{uid}/bus"
    return uid, dbus


def tomar_captura_simple():
    timestamp      = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_archivo = f"captura_{timestamp}.png"
    ruta_completa  = os.path.join(CARPETA_CAPTURAS, nombre_archivo)
    print(f"[Camara] Tomando captura: {nombre_archivo}")
    uid, dbus = obtener_uid_dbus()
    subprocess.run([
        "sudo", "-u", USUARIO, "env",
        "DISPLAY=:0",
        f"DBUS_SESSION_BUS_ADDRESS={dbus}",
        f"HOME=/home/{USUARIO}",
        f"XDG_RUNTIME_DIR=/run/user/{uid}",
        "gnome-screenshot", "--file", ruta_completa,
    ], capture_output=True, text=True)
    if os.path.exists(ruta_completa):
        print(f"[OK] Captura guardada: {ruta_completa}")
        return nombre_archivo, ruta_completa
    print("[X] No se guardo la captura.")
    return None, None


def hacer_scroll_abajo(uid, dbus):
    subprocess.run([
        "sudo", "-u", USUARIO, "env",
        "DISPLAY=:0",
        f"DBUS_SESSION_BUS_ADDRESS={dbus}",
        f"XDG_RUNTIME_DIR=/run/user/{uid}",
        "xdotool", "click", "--clearmodifiers", "5",
    ], capture_output=True)


def tomar_capturas_con_scroll(num_capturas=4, pausa=0.6, scroll_clicks=8):
    try:
        from PIL import Image
    except ImportError:
        print("[X] Pillow no instalado: pip install Pillow")
        return None, None
    uid, dbus = obtener_uid_dbus()
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    rutas      = []
    print(f"[Scroll] Tomando {num_capturas} capturas con scroll...")
    for i in range(num_capturas):
        nombre = f"scroll_{timestamp}_{i+1}.png"
        ruta   = os.path.join(CARPETA_CAPTURAS, nombre)
        subprocess.run([
            "sudo", "-u", USUARIO, "env", "DISPLAY=:0",
            f"DBUS_SESSION_BUS_ADDRESS={dbus}",
            f"HOME=/home/{USUARIO}",
            f"XDG_RUNTIME_DIR=/run/user/{uid}",
            "gnome-screenshot", "--file", ruta,
        ], capture_output=True)
        if os.path.exists(ruta):
            rutas.append(ruta)
            print(f"[OK] Captura {i+1}/{num_capturas} tomada.")
        if i < num_capturas - 1:
            time.sleep(pausa)
            for _ in range(scroll_clicks):
                hacer_scroll_abajo(uid, dbus)
            time.sleep(pausa)
    if not rutas:
        return None, None
    imagenes   = [Image.open(r) for r in rutas]
    ancho_max  = max(img.width for img in imagenes)
    alto_total = sum(img.height for img in imagenes)
    combinada  = Image.new("RGB", (ancho_max, alto_total))
    y_offset = 0
    for img in imagenes:
        combinada.paste(img, (0, y_offset))
        y_offset += img.height
    nombre_final = f"scroll_combinada_{timestamp}.png"
    ruta_final   = os.path.join(CARPETA_CAPTURAS, nombre_final)
    combinada.save(ruta_final)
    for r in rutas:
        os.remove(r)
    print(f"[OK] Imagen combinada guardada: {ruta_final}")
    return nombre_final, ruta_final


def preguntar_a_gpt4o(ruta_imagen):
    print("[GPT-4o] Enviando imagen para analisis...")
    with open(ruta_imagen, "rb") as f:
        imagen_b64 = base64.b64encode(f.read()).decode("utf-8")
    payload = json.dumps({
        "model": "gpt-4o",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{imagen_b64}", "detail": "high"}},
                {"type": "text", "text": (
                    "Read all visible text and code in this screenshot. "
                    "IMPORTANT: Detect the language of the question or exercise and respond in that same language. "
                    "If the content is in Spanish, respond in Spanish. If it is in English, respond in English. "
                    "If there is a coding exercise, solve it directly: write the complete and correct code. "
                    "If there is a conceptual question, answer it directly and concisely. "
                    "Do NOT describe or restate what you see. Go straight to the solution. "
                    "If the answer is code, write only the necessary code with a brief explanation."
                )}
            ]
        }],
        "max_tokens": 1000
    }).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_API_URL, data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
            print("[OK] Respuesta recibida de GPT-4o.")
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        print(f"[X] Error HTTP {e.code}: {e.read().decode()}")
        return f"Error al consultar GPT-4o ({e.code})."
    except Exception as e:
        return f"Error de conexion: {str(e)}"


def abrir_yad(uid, dbus, titulo, respuesta):
    """
    Abre una ventana yad escribiendo la respuesta en un archivo temporal.
    Usa --filename en lugar de stdin para evitar problemas con pipes.
    Retorna el proceso Popen.
    """
    # Escribir respuesta en archivo temporal
    tmp = f"/tmp/yad_resp_{uid}.txt"
    with open(tmp, "w") as f:
        f.write(respuesta)

    proc = subprocess.Popen([
        "sudo", "-u", USUARIO, "env",
        "DISPLAY=:0",
        f"DBUS_SESSION_BUS_ADDRESS={dbus}",
        f"XDG_RUNTIME_DIR=/run/user/{uid}",
        "yad", "--text-info",
        "--title", titulo,
        "--fontname=Monospace 11",
        "--width=620", "--height=400",
        "--button=Cerrar:0", "--wrap",
        f"--filename={tmp}",
    ])
    return proc


def mostrar_ventana_alerta(nombre_archivo, respuesta):
    """Abre una ventana nueva cada vez. Usada por 1+X."""
    try:
        uid, dbus = obtener_uid_dbus()
        abrir_yad(uid, dbus, TITULO, respuesta)
        print("[OK] Ventana mostrada.")
    except Exception as e:
        print(f"[X] Error al mostrar ventana: {e}")


def mostrar_ventana_permanente(respuesta):
    """
    Cierra la ventana anterior y abre una nueva con el contenido actualizado.
    Obtiene el PID de yad (hijo de sudo) y lo mata directamente con sudo kill.
    Usada por 3+X.
    """
    global _ventana_proc
    try:
        uid, dbus = obtener_uid_dbus()
        with _ventana_lock:
            if _ventana_proc is not None and _ventana_proc.poll() is None:
                print("[OK] Cerrando ventana anterior...")
                # Obtener PID de yad (proceso hijo de sudo)
                try:
                    resultado = subprocess.run(
                        ["pgrep", "-P", str(_ventana_proc.pid)],
                        capture_output=True, text=True
                    )
                    yad_pid = resultado.stdout.strip()
                    if yad_pid:
                        subprocess.run(["sudo", "kill", yad_pid], capture_output=True)
                except Exception:
                    pass
                # Matar sudo tambien
                _ventana_proc.terminate()
                try:
                    _ventana_proc.wait(timeout=2)
                except Exception:
                    pass
            # Abrir nueva ventana
            _ventana_proc = abrir_yad(uid, dbus, f"{TITULO} [Permanente]", respuesta)
            print("[OK] Ventana permanente actualizada.")
    except Exception as e:
        print(f"[X] Error en ventana permanente: {e}")


def manejar_evento_simple():
    try:
        nombre_archivo, ruta_completa = tomar_captura_simple()
        if not ruta_completa:
            return
        respuesta = preguntar_a_gpt4o(ruta_completa)
        mostrar_ventana_alerta(nombre_archivo, respuesta)
    except Exception as e:
        print(f"[X] Error en flujo simple: {e}")


def manejar_evento_permanente():
    try:
        nombre_archivo, ruta_completa = tomar_captura_simple()
        if not ruta_completa:
            return
        respuesta = preguntar_a_gpt4o(ruta_completa)
        mostrar_ventana_permanente(respuesta)
    except Exception as e:
        print(f"[X] Error en flujo permanente: {e}")


def manejar_evento_scroll():
    try:
        print("[Scroll] Iniciando en 2 segundos... enfoca la ventana del test.")
        time.sleep(2)
        nombre_archivo, ruta_completa = tomar_capturas_con_scroll()
        if not ruta_completa:
            return
        respuesta = preguntar_a_gpt4o(ruta_completa)
        mostrar_ventana_alerta(nombre_archivo, respuesta)
    except Exception as e:
        print(f"[X] Error en flujo scroll: {e}")


def encontrar_teclado():
    try:
        dev = evdev.InputDevice("/dev/input/event2")
        print(f"[OK] Teclado: {dev.name} ({dev.path})")
        return dev
    except Exception as e:
        print(f"[X] No se pudo abrir el teclado: {e}")
        return None


def main():
    dev = encontrar_teclado()
    if not dev:
        sys.exit(1)
    if not os.path.exists(CARPETA_CAPTURAS):
        print(f"[X] Carpeta no encontrada: {CARPETA_CAPTURAS}")
        sys.exit(1)

    print("=" * 60)
    print(f"  Teclado : {dev.name} ({dev.path})")
    print(f"  Capturas: {CARPETA_CAPTURAS}")
    print(f"  Usuario : {USUARIO}")
    print(f"  IA      : GPT-4o Vision")
    print("  1+X     : captura simple -> ventana nueva")
    print("  3+X     : captura simple -> cierra anterior, abre nueva")
    print("  5+X     : scroll + capturas combinadas -> ventana nueva")
    print("  Salir   : Ctrl+C")
    print("=" * 60)

    uno_activo   = False
    tres_activo  = False
    cinco_activo = False

    try:
        for evento in dev.read_loop():
            if evento.type != ecodes.EV_KEY:
                continue
            key_event = evdev.categorize(evento)

            if key_event.scancode == KEY_1:
                uno_activo = (key_event.keystate != 0)
            if key_event.scancode == KEY_3:
                tres_activo = (key_event.keystate != 0)
            if key_event.scancode == KEY_5:
                cinco_activo = (key_event.keystate != 0)

            if key_event.scancode == KEY_X and key_event.keystate == 1:
                if uno_activo:
                    print("[Hotkey] 1+X -> captura simple")
                    threading.Thread(target=manejar_evento_simple, daemon=True).start()
                elif tres_activo:
                    print("[Hotkey] 3+X -> ventana permanente")
                    threading.Thread(target=manejar_evento_permanente, daemon=True).start()
                elif cinco_activo:
                    print("[Hotkey] 5+X -> captura con scroll")
                    threading.Thread(target=manejar_evento_scroll, daemon=True).start()

    except KeyboardInterrupt:
        print("\n[!] Script detenido.")
    except PermissionError:
        print("\n[X] Ejecuta con: sudo python3 hotkey_notifier_wayland.py")


if __name__ == "__main__":
    main()