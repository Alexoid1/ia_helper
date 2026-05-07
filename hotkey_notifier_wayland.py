#!/usr/bin/env python3
"""
Hotkey Notifier - Compatible con Wayland
Hotkeys:
  1+X  -> Captura simple + GPT-4o + alerta
  5+X  -> Capturas con scroll automatico, combina en una imagen larga + GPT-4o + alerta

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
    """
    Lee el archivo .env ubicado en la misma carpeta del script y carga
    las variables de entorno. Esto evita hardcodear datos sensibles como
    API keys en el codigo fuente y que se suban al repositorio.
    """
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
CARPETA_CAPTURAS = os.path.join( os.path.dirname(os.path.abspath(__file__)),"capturas")
USUARIO          = "pablo"
OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY")
OPENAI_API_URL   = "https://api.openai.com/v1/chat/completions"

if not OPENAI_API_KEY:
    print("[X] OPENAI_API_KEY no encontrada en el archivo .env")
    sys.exit(1)

# Codigos de teclas
KEY_X   = ecodes.KEY_X
KEY_1   = ecodes.KEY_1   # hotkey simple
KEY_5   = ecodes.KEY_5   # hotkey scroll


def obtener_uid_dbus():
    """
    Obtiene el UID del usuario real y la direccion D-Bus de su sesion grafica.
    Necesario para lanzar apps graficas desde un proceso sudo.
    Retorna: (uid, dbus_address)
    """
    uid  = subprocess.check_output(["id", "-u", USUARIO]).decode().strip()
    dbus = f"unix:path=/run/user/{uid}/bus"
    return uid, dbus


def tomar_captura_simple():
    """
    Toma una captura de pantalla completa con gnome-screenshot y la guarda
    en CARPETA_CAPTURAS con nombre basado en timestamp.
    Retorna: (nombre_archivo, ruta_completa) o (None, None) si falla.
    """
    timestamp      = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_archivo = f"captura_{timestamp}.png"
    ruta_completa  = os.path.join(CARPETA_CAPTURAS, nombre_archivo)

    print(f"[Camara] Tomando captura: {nombre_archivo}")

    uid, dbus = obtener_uid_dbus()

    resultado = subprocess.run(
        [
            "sudo", "-u", USUARIO,
            "env",
            "DISPLAY=:0",
            f"DBUS_SESSION_BUS_ADDRESS={dbus}",
            f"HOME=/home/{USUARIO}",
            f"XDG_RUNTIME_DIR=/run/user/{uid}",
            "gnome-screenshot",
            "--file", ruta_completa,
        ],
        capture_output=True,
        text=True
    )

    if os.path.exists(ruta_completa):
        print(f"[OK] Captura guardada: {ruta_completa}")
        return nombre_archivo, ruta_completa
    else:
        print(f"[X] No se guardo. stderr: {resultado.stderr.strip()}")
        return None, None


def hacer_scroll_abajo(uid, dbus, pixeles=500):
    """
    Simula scroll hacia abajo en la ventana activa usando xdotool.
    Se usa para avanzar el contenido de la pagina antes de cada captura.
    Parametros:
      - pixeles: cantidad de scroll (equivale a clicks de rueda del mouse)
    """
    subprocess.run([
        "sudo", "-u", USUARIO,
        "env",
        "DISPLAY=:0",
        f"DBUS_SESSION_BUS_ADDRESS={dbus}",
        f"XDG_RUNTIME_DIR=/run/user/{uid}",
        "xdotool", "click", "--clearmodifiers", "5",  # boton 5 = scroll abajo
    ], capture_output=True)


def tomar_capturas_con_scroll(num_capturas=4, pausa=0.6, scroll_clicks=8):
    """
    Toma multiples capturas haciendo scroll automatico entre cada una.
    Luego combina todas las imagenes verticalmente en una sola imagen larga
    usando Python PIL/Pillow, para que GPT-4o vea el contenido completo.
    Parametros:
      - num_capturas: cuantas capturas tomar (default 4)
      - pausa: segundos entre captura y scroll (default 0.6)
      - scroll_clicks: cuantos clicks de scroll entre capturas (default 8)
    Retorna: (nombre_archivo_combinado, ruta_completa) o (None, None) si falla.
    """
    try:
        from PIL import Image
    except ImportError:
        print("[X] Pillow no instalado. Instala con: pip install Pillow")
        return None, None

    uid, dbus = obtener_uid_dbus()
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    rutas      = []

    print(f"[Scroll] Tomando {num_capturas} capturas con scroll...")

    for i in range(num_capturas):
        nombre = f"scroll_{timestamp}_{i+1}.png"
        ruta   = os.path.join(CARPETA_CAPTURAS, nombre)

        # Tomar captura
        subprocess.run([
            "sudo", "-u", USUARIO,
            "env", "DISPLAY=:0",
            f"DBUS_SESSION_BUS_ADDRESS={dbus}",
            f"HOME=/home/{USUARIO}",
            f"XDG_RUNTIME_DIR=/run/user/{uid}",
            "gnome-screenshot", "--file", ruta,
        ], capture_output=True)

        if os.path.exists(ruta):
            rutas.append(ruta)
            print(f"[OK] Captura {i+1}/{num_capturas} tomada.")
        else:
            print(f"[X] Fallo captura {i+1}.")

        # Hacer scroll antes de la siguiente captura (excepto en la ultima)
        if i < num_capturas - 1:
            time.sleep(pausa)
            for _ in range(scroll_clicks):
                hacer_scroll_abajo(uid, dbus)
            time.sleep(pausa)

    if not rutas:
        print("[X] No se tomaron capturas.")
        return None, None

    # Combinar todas las imagenes verticalmente en una sola
    print(f"[Scroll] Combinando {len(rutas)} imagenes...")
    imagenes     = [Image.open(r) for r in rutas]
    ancho_max    = max(img.width for img in imagenes)
    alto_total   = sum(img.height for img in imagenes)
    combinada    = Image.new("RGB", (ancho_max, alto_total))

    y_offset = 0
    for img in imagenes:
        combinada.paste(img, (0, y_offset))
        y_offset += img.height

    # Guardar imagen combinada
    nombre_final = f"scroll_combinada_{timestamp}.png"
    ruta_final   = os.path.join(CARPETA_CAPTURAS, nombre_final)
    combinada.save(ruta_final)

    # Eliminar capturas parciales
    for r in rutas:
        os.remove(r)

    print(f"[OK] Imagen combinada guardada: {ruta_final}")
    return nombre_final, ruta_final


def preguntar_a_gpt4o(ruta_imagen):
    """
    Envia la imagen a GPT-4o Vision de OpenAI codificada en base64.
    El prompt detecta el idioma del contenido y responde en ese idioma.
    Si hay ejercicio de codigo lo resuelve directamente.
    Si hay pregunta conceptual responde conciso y directo.
    Retorna: string con la respuesta, o mensaje de error.
    """
    print(f"[GPT-4o] Enviando imagen para analisis...")

    with open(ruta_imagen, "rb") as f:
        imagen_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = json.dumps({
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{imagen_b64}",
                            "detail": "high"
                        }
                    },
                    {
                        "type": "text",
                        "text": (
                            "Read all visible text and code in this screenshot. "
                            "IMPORTANT: Detect the language of the question or exercise and respond in that same language. "
                            "If the content is in Spanish, respond in Spanish. If it is in English, respond in English. "
                            "If there is a coding exercise, solve it directly: write the complete and correct code. "
                            "If there is a conceptual question, answer it directly and concisely. "
                            "Do NOT describe or restate what you see. Go straight to the solution. "
                            "If the answer is code, write only the necessary code with a brief explanation."
                        )
                    }
                ]
            }
        ],
        "max_tokens": 1000
    }).encode("utf-8")

    req = urllib.request.Request(
        OPENAI_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data     = json.loads(response.read().decode("utf-8"))
            respuesta = data["choices"][0]["message"]["content"]
            print(f"[OK] Respuesta recibida de GPT-4o.")
            return respuesta

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"[X] Error HTTP {e.code}: {error_body}")
        return f"Error al consultar GPT-4o ({e.code})."

    except Exception as e:
        print(f"[X] Error: {e}")
        return f"Error de conexion: {str(e)}"


def mostrar_ventana_alerta(nombre_archivo, respuesta):
    """
    Muestra la respuesta de GPT-4o en una ventana yad en modo --text-info.
    Acepta cualquier caracter especial sin errores de markup.
    La respuesta se pasa por stdin via pipe.
    """
    try:
        uid, dbus = obtener_uid_dbus()

        echo_proc = subprocess.Popen(
            ["echo", respuesta],
            stdout=subprocess.PIPE
        )
        subprocess.Popen([
            "sudo", "-u", USUARIO,
            "env",
            "DISPLAY=:0",
            f"DBUS_SESSION_BUS_ADDRESS={dbus}",
            f"XDG_RUNTIME_DIR=/run/user/{uid}",
            "yad",
            "--text-info",
            "--title", TITULO,
            "--fontname=Monospace 11",
            "--width=620",
            "--height=400",
            "--button=Cerrar:0",
            "--wrap",
        ], stdin=echo_proc.stdout)
        print(f"[OK] Ventana mostrada.")

    except Exception as e:
        print(f"[X] Error al mostrar ventana: {e}")


def manejar_evento_simple():
    """
    Flujo para 1+X:
      1. Toma una captura simple.
      2. Envia a GPT-4o.
      3. Muestra respuesta en ventana.
    """
    try:
        nombre_archivo, ruta_completa = tomar_captura_simple()
        if not ruta_completa:
            mostrar_ventana_alerta("error", "No se pudo tomar la captura.")
            return
        respuesta = preguntar_a_gpt4o(ruta_completa)
        mostrar_ventana_alerta(nombre_archivo, respuesta)
    except Exception as e:
        print(f"[X] Error en flujo simple: {e}")


def manejar_evento_scroll():
    """
    Flujo para 5+X:
      1. Toma 4 capturas haciendo scroll automatico entre cada una.
      2. Combina todas en una sola imagen larga con Pillow.
      3. Envia la imagen combinada a GPT-4o.
      4. Muestra respuesta en ventana.
    Util cuando la pregunta tiene mucho contenido y requiere scroll para verla completa.
    """
    try:
        print("[Scroll] Iniciando captura con scroll en 2 segundos... enfoca la ventana del test.")
        time.sleep(2)  # dar tiempo al usuario para enfocar la ventana correcta
        nombre_archivo, ruta_completa = tomar_capturas_con_scroll()
        if not ruta_completa:
            mostrar_ventana_alerta("error", "No se pudieron tomar las capturas con scroll.")
            return
        respuesta = preguntar_a_gpt4o(ruta_completa)
        mostrar_ventana_alerta(nombre_archivo, respuesta)
    except Exception as e:
        print(f"[X] Error en flujo scroll: {e}")


def encontrar_teclado():
    """
    Retorna el teclado principal usando su path fijo /dev/input/event2
    (AT Translated Set 2 keyboard identificado en este sistema).
    Retorna: objeto InputDevice o None si falla.
    """
    try:
        dev = evdev.InputDevice("/dev/input/event2")
        print(f"[OK] Teclado encontrado: {dev.name} ({dev.path})")
        return dev
    except Exception as e:
        print(f"[X] No se pudo abrir el teclado: {e}")
        return None


def main():
    """
    Punto de entrada. Valida teclado y carpeta, luego escucha el teclado:
      - 1+X -> captura simple
      - 5+X -> capturas con scroll combinadas
    Cada hotkey lanza su flujo en un hilo separado.
    """
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
    print("  1+X     : captura simple -> GPT-4o -> alerta")
    print("  5+X     : scroll + capturas combinadas -> GPT-4o -> alerta")
    print("  Salir   : Ctrl+C")
    print("=" * 60)

    uno_activo  = False  # rastrea si la tecla 1 esta presionada
    cinco_activo = False  # rastrea si la tecla 5 esta presionada

    try:
        for evento in dev.read_loop():
            if evento.type != ecodes.EV_KEY:
                continue

            key_event = evdev.categorize(evento)

            # Actualizar estado de tecla 1
            if key_event.scancode == KEY_1:
                uno_activo = (key_event.keystate != 0)

            # Actualizar estado de tecla 5
            if key_event.scancode == KEY_5:
                cinco_activo = (key_event.keystate != 0)

            # Detectar 1+X
            if (key_event.scancode == KEY_X
                    and key_event.keystate == 1
                    and uno_activo):
                print("[Hotkey] 1+X detectado -> captura simple")
                threading.Thread(target=manejar_evento_simple, daemon=True).start()

            # Detectar 5+X
            if (key_event.scancode == KEY_X
                    and key_event.keystate == 1
                    and cinco_activo):
                print("[Hotkey] 5+X detectado -> captura con scroll")
                threading.Thread(target=manejar_evento_scroll, daemon=True).start()

    except KeyboardInterrupt:
        print("\n[!] Script detenido.")
    except PermissionError:
        print("\n[X] Ejecuta con: sudo python3 hotkey_notifier_wayland.py")


if __name__ == "__main__":
    main()