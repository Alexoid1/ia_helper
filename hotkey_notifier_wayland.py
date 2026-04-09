#!/usr/bin/env python3
"""
Hotkey Notifier - Compatible con Wayland
Al presionar 1+X:
  1. Toma una captura con gnome-screenshot
  2. La guarda en /capturas/
  3. Envia la imagen a GPT-4o Vision
  4. GPT-4o lee el texto, detecta preguntas y responde
  5. Muestra la respuesta en ventana de alerta

Uso:
    sudo python3 hotkey_notifier_wayland.py
"""

import sys
import os
import threading
import subprocess
import json
import base64
import urllib.request
import urllib.error
from datetime import datetime
import evdev
from evdev import ecodes

# ── Configuracion ──────────────────────────────────────────────────────────────
TITULO           = "GPT-4o Responde"
CARPETA_CAPTURAS = "/home/pablo/Escritorio/coding-challenges/easy-test/capturas"
USUARIO          = "pablo"
OPENAI_API_KEY   = "REMOVED"
OPENAI_API_URL   = "https://api.openai.com/v1/chat/completions"

# Codigos de teclas que se escuchan (1+X)
KEY_X   = ecodes.KEY_X
KEY_1   = ecodes.KEY_1


def obtener_uid_dbus():
    """
    Obtiene el UID del usuario real (no root) y construye la direccion del
    bus de sesion D-Bus. Esto es necesario para poder lanzar aplicaciones
    graficas (gnome-screenshot, yad) desde un proceso que corre con sudo,
    ya que necesitan conectarse a la sesion grafica del usuario.
    Retorna: (uid, dbus_address)
    """
    uid  = subprocess.check_output(["id", "-u", USUARIO]).decode().strip()
    dbus = f"unix:path=/run/user/{uid}/bus"
    return uid, dbus


def tomar_captura():
    """
    Toma una captura de pantalla completa usando gnome-screenshot y la guarda
    en la carpeta CARPETA_CAPTURAS con un nombre unico basado en la fecha y hora.
    El comando se ejecuta como el usuario real (no root) para tener acceso
    a la sesion grafica de Wayland.
    Retorna: (nombre_archivo, ruta_completa) o (None, None) si falla.
    """
    # Generar nombre unico con timestamp
    timestamp      = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_archivo = f"captura_{timestamp}.png"
    ruta_completa  = os.path.join(CARPETA_CAPTURAS, nombre_archivo)

    print(f"[Camara] Tomando captura: {nombre_archivo}")

    uid, dbus = obtener_uid_dbus()

    # Ejecutar gnome-screenshot como el usuario real con las variables
    # de entorno necesarias para acceder a la sesion grafica
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

    # Verificar que el archivo fue creado exitosamente
    if os.path.exists(ruta_completa):
        print(f"[OK] Captura guardada: {ruta_completa}")
        return nombre_archivo, ruta_completa
    else:
        print(f"[X] No se guardo. stderr: {resultado.stderr.strip()}")
        return None, None


def preguntar_a_gpt4o(ruta_imagen):
    """
    Envia la imagen capturada a la API de GPT-4o Vision de OpenAI en base64.
    El prompt le indica al modelo que:
      - Si encuentra un ejercicio de codigo, lo resuelva directamente.
      - Si encuentra una pregunta conceptual, la responda en español.
      - No describa ni reformule, sino que vaya directo a la solucion.
    Retorna: string con la respuesta de GPT-4o, o mensaje de error.
    """
    print(f"[GPT-4o] Enviando imagen para analisis...")

    # Leer la imagen y convertirla a base64 para enviarla en el payload JSON
    with open(ruta_imagen, "rb") as f:
        imagen_b64 = base64.b64encode(f.read()).decode("utf-8")

    # Construir el payload con el modelo, la imagen y el prompt
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
                            "detail": "high"  # alta resolucion para leer codigo
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
        "max_tokens": 500
    }).encode("utf-8")

    # Crear la request HTTP con autenticacion Bearer
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
        with urllib.request.urlopen(req, timeout=40) as response:
            data = json.loads(response.read().decode("utf-8"))
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
    Muestra la respuesta de GPT-4o en una ventana grafica usando yad.
    Se usa yad en modo --text-info porque acepta cualquier caracter especial
    ({, }, <, >, ', etc.) sin errores de markup, ideal para mostrar codigo.
    La respuesta se pasa por stdin via pipe desde echo para evitar
    limitaciones de longitud en argumentos de linea de comandos.
    """
    try:
        uid, dbus = obtener_uid_dbus()

        # Pasar el texto a yad mediante un pipe desde echo
        # yad --text-info lee su contenido desde stdin
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
            "--text-info",       # modo visor de texto, acepta caracteres especiales
            "--title", TITULO,
            "--fontname=Monospace 11",  # fuente monospace para codigo
            "--width=620",
            "--height=400",
            "--geometry=620x400+300+250",  # posicion: X=900, Y=250
            "--button=Cerrar:0",
            "--wrap",            # ajuste de linea automatico
        ], stdin=echo_proc.stdout)
        print(f"[OK] Ventana mostrada.")

    except Exception as e:
        print(f"[X] Error al mostrar ventana: {e}")


def manejar_evento():
    """
    Orquesta el flujo completo que se ejecuta cada vez que se presiona 1+X:
      1. Llama a tomar_captura() para obtener la imagen.
      2. Llama a preguntar_a_gpt4o() para analizar la imagen.
      3. Llama a mostrar_ventana_alerta() para mostrar la respuesta.
    Se ejecuta en un hilo separado para no bloquear la escucha del teclado.
    """
    try:
        # Paso 1: tomar la captura
        nombre_archivo, ruta_completa = tomar_captura()

        if not ruta_completa:
            mostrar_ventana_alerta("error", "No se pudo tomar la captura.")
            return

        # Paso 2: enviar a GPT-4o y obtener respuesta
        respuesta = preguntar_a_gpt4o(ruta_completa)

        # Paso 3: mostrar resultado en ventana
        mostrar_ventana_alerta(nombre_archivo, respuesta)

    except Exception as e:
        print(f"[X] Error en el flujo: {e}")


def encontrar_teclado():
    """
    Busca automaticamente el primer dispositivo de teclado disponible
    en /dev/input/ usando evdev. Identifica un teclado verificando que
    el dispositivo tenga las teclas KEY_A y KEY_SPACE en sus capacidades,
    lo que descarta mice, touchpads y otros dispositivos de entrada.
    Retorna: objeto InputDevice del teclado, o None si no se encuentra.
    """
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        caps = dev.capabilities()
        if ecodes.EV_KEY in caps:
            keys = caps[ecodes.EV_KEY]
            # Verificar que tiene teclas tipicas de un teclado
            if ecodes.KEY_A in keys and ecodes.KEY_SPACE in keys:
                return dev
    return None


def main():
    """
    Punto de entrada del script. Realiza las validaciones iniciales
    (teclado disponible, carpeta de capturas existente) y luego inicia
    el bucle principal de escucha de eventos del teclado.
    Detecta cuando se presionan 1+X simultaneamente y lanza
    manejar_evento() en un hilo separado para no bloquear el bucle.
    """
    # Buscar teclado disponible
    dev = encontrar_teclado()
    if not dev:
        print("[X] No se encontro ningun teclado.")
        sys.exit(1)

    # Verificar que la carpeta de capturas existe
    if not os.path.exists(CARPETA_CAPTURAS):
        print(f"[X] Carpeta no encontrada: {CARPETA_CAPTURAS}")
        sys.exit(1)

    print("=" * 60)
    print(f"  Teclado : {dev.name} ({dev.path})")
    print(f"  Capturas: {CARPETA_CAPTURAS}")
    print(f"  Usuario : {USUARIO}")
    print(f"  IA      : GPT-4o Vision")
    print("  Flujo   : 1+X -> captura -> GPT-4o -> alerta")
    print("  Salir   : Ctrl+C")
    print("=" * 60)

    uno_activo = False  # rastrea si la tecla 1 esta presionada

    try:
        # Bucle principal: leer eventos del teclado indefinidamente
        for evento in dev.read_loop():
            # Ignorar eventos que no son de teclado
            if evento.type != ecodes.EV_KEY:
                continue

            key_event = evdev.categorize(evento)

            # Actualizar estado de la tecla 1 (presionada o soltada)
            if key_event.scancode == KEY_1:
                uno_activo = (key_event.keystate != 0)  # 0=soltado, 1=presionado, 2=repetido

            # Detectar 1+X: X presionada (keystate==1) mientras 1 esta activa
            if (key_event.scancode == KEY_X
                    and key_event.keystate == 1
                    and uno_activo):
                # Lanzar en hilo separado para no bloquear la escucha
                threading.Thread(target=manejar_evento, daemon=True).start()

    except KeyboardInterrupt:
        print("\n[!] Script detenido.")
    except PermissionError:
        print("\n[X] Ejecuta con: sudo python3 hotkey_notifier_wayland.py")


if __name__ == "__main__":
    main()