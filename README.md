# 🖥️ Hotkey Notifier con GPT-4o Vision

Script para Ubuntu con Wayland que al presionar **Ctrl+X**:
1. Toma una captura de pantalla
2. La guarda en la carpeta `capturas/`
3. Envía la imagen a GPT-4o Vision
4. Muestra la respuesta en una ventana de alerta

---

## 📋 Requisitos del sistema

- Ubuntu con sesión **Wayland**
- Python 3.8+
- Conexión a internet

---

## 📦 Instalación de dependencias

### 1. Dependencias del sistema

```bash
sudo apt install gnome-screenshot yad
```

| Herramienta | Función |
|---|---|
| `gnome-screenshot` | 
| `yad` | 

### 2. Dependencias de Python

```bash
pip install evdev
```

| Librería |
|---|---|
| `evdev` | 

---


## ⚙️ Configuración

Abre el script y edita las siguientes variables al inicio:

```python
TITULO           = "GPT-4o Responde"       # Título de la ventana de alerta
CARPETA_CAPTURAS = "/ruta/a/tu/capturas"   # Ruta absoluta a la carpeta capturas/
USUARIO          = "tu_usuario"            # Tu usuario de Ubuntu (no root)
OPENAI_API_KEY   = "sk-..."               # Tu API key de OpenAI
```

### ¿Cómo obtener una API key de OpenAI?

1. Entra a [platform.openai.com](https://platform.openai.com)
2. Ve a **API Keys** → **Create new secret key**
3. Copia la key y pégala en `OPENAI_API_KEY`

---

## 🚀 Uso

### Ejecutar el script

```bash
sudo python3 hotkey_notifier_wayland.py
```

> ⚠️ Se necesita `sudo` porque leer eventos del teclado a nivel global en Wayland requiere permisos de root para acceder a `/dev/input/`.

### Verás este mensaje cuando esté listo

```
============================================================
  Teclado : AT Translated Set 2 keyboard (/dev/input/event2)
  Capturas: /home/pablo/.../capturas
  Usuario : pablo
  IA      : GPT-4o Vision
  Flujo   : Ctrl+X -> captura -> GPT-4o -> alerta
  Salir   : Ctrl+C
============================================================
```

### Usar el hotkey

1. Presiona **Ctrl+X** desde cualquier ventana o aplicación
2. El script toma la captura automáticamente
3. Espera unos segundos mientras GPT-4o analiza la imagen
4. Aparece la ventana con la respuesta

### Detener el script

```bash
# En la terminal donde corre el script:
Ctrl+C

# O desde otra terminal:
sudo pkill -f hotkey_notifier_wayland.py
```

---



## 🔧 Solución de problemas

### El script no detecta el teclado

Lista los dispositivos disponibles:

```bash
sudo python3 -c "
import evdev
for path in evdev.list_devices():
    dev = evdev.InputDevice(path)
    print(path, dev.name)
"
```

Busca el que diga `keyboard` en el nombre.

### gnome-screenshot no funciona

Verifica que está instalado:

```bash
which gnome-screenshot
gnome-screenshot --file /tmp/prueba.png && echo "OK"
```

### La ventana no aparece

Verifica que `yad` está instalado:

```bash
sudo apt install yad
yad --info --text="Prueba"
```

### Error de permisos en la carpeta capturas

```bash
sudo chown -R $USER:$USER /ruta/a/tu/capturas
```

---

## 🛠️ Tecnologías utilizadas

| Tecnología | Versión | Uso |
|---|---|---|
| Python | 3.8+ | Lenguaje del script |
| evdev | latest | Escucha global del teclado en Wayland |
| gnome-screenshot | - | Captura de pantalla |
| GPT-4o Vision | OpenAI API | Análisis de imagen y respuesta |
| yad | - | Ventana de alerta gráfica |
