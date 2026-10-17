"""
LocalRouterLLM
==============
Smart On-Demand Model Router & VRAM Manager for Llama.cpp and Local AI Agents.
- Compatible with OpenCode, Continue.dev, Aider, Cline, and any OpenAI API client.
- Dynamic single-model VRAM management (0% VRAM when idle).
- Configurable auto-unload timer.
- Interactive Windows System Tray icon with 1-click VRAM flush.
- Built-in Web Dashboard at http://127.0.0.1:8080/
- Single-instance mutex protection and auto-recovery from stale ports.
"""

import os
import sys
import json
import time
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.error
import urllib.parse
from collections import deque
import socket
import webbrowser
import logging

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    import tkinter as tk
    HAS_TK = True
except ImportError:
    HAS_TK = False

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
EXAMPLE_CONFIG_PATH = os.path.join(BASE_DIR, "config.example.json")
LOG_PATH = os.path.join(BASE_DIR, "router.log")

# Configurar logging dual a archivo y consola
logger = logging.getLogger("LocalRouterLLM")
logger.setLevel(logging.INFO)
logger.handlers.clear()
log_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

try:
    fh = logging.FileHandler(LOG_PATH, mode="a", encoding="utf-8")
    fh.setFormatter(log_formatter)
    logger.addHandler(fh)
except Exception:
    pass

sh = logging.StreamHandler(sys.stdout)
sh.setFormatter(log_formatter)
logger.addHandler(sh)

def log_info(msg):
    logger.info(msg)

def log_warn(msg):
    logger.warning(msg)

def log_err(msg):
    logger.error(msg)

def load_config():
    path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else EXAMPLE_CONFIG_PATH
    if not os.path.exists(path):
        log_err(f"No se encontró archivo de configuración en {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

CONFIG = load_config()
SERVER_CFG = CONFIG.get("server", {})
LLAMA_CFG = CONFIG.get("llama_cpp", {})
MODELS_CONFIG = CONFIG.get("models", {})

ROUTER_HOST = SERVER_CFG.get("host", "127.0.0.1")
ROUTER_PORT = int(SERVER_CFG.get("port", 8080))
LLAMA_PORT = int(SERVER_CFG.get("llama_port", 8081))
IDLE_TIMEOUT_SECONDS = int(SERVER_CFG.get("idle_timeout_minutes", 40)) * 60
START_TIME = time.time()

# Resolver rutas relativas con respaldo automático al directorio del sistema
BIN_PATH = os.path.abspath(os.path.join(BASE_DIR, LLAMA_CFG.get("executable", "llama-server.exe")))
if not os.path.exists(BIN_PATH):
    fallback_bin = r"c:\Program Files\LlamaCPP\bin\llama-b11065-bin-win-cuda-13.4-x64\llama-server.exe"
    if os.path.exists(fallback_bin):
        BIN_PATH = fallback_bin
BIN_DIR = os.path.dirname(BIN_PATH)

MODELS_DIR = os.path.abspath(os.path.join(BASE_DIR, LLAMA_CFG.get("models_dir", "../gguf")))

def resolve_model_path(rel_or_abs):
    if not rel_or_abs:
        return None
    if os.path.isabs(rel_or_abs):
        return rel_or_abs
    primary = os.path.normpath(os.path.join(MODELS_DIR, rel_or_abs))
    if os.path.exists(primary):
        return primary
    fallback = os.path.normpath(os.path.join(r"c:\Program Files\LlamaCPP\gguf", rel_or_abs))
    if os.path.exists(fallback):
        return fallback
    return primary

def resolve_bin_path(rel_or_abs):
    if not rel_or_abs:
        return BIN_PATH
    if os.path.isabs(rel_or_abs) and os.path.exists(rel_or_abs):
        return rel_or_abs
    primary = os.path.normpath(os.path.join(BASE_DIR, rel_or_abs))
    if os.path.exists(primary):
        return primary
    cleaned = rel_or_abs
    while cleaned.startswith("../") or cleaned.startswith("..\\"):
        cleaned = cleaned[3:]
    fallback = os.path.normpath(os.path.join(r"c:\Program Files\LlamaCPP", cleaned))
    if os.path.exists(fallback):
        return fallback
    fallback_bin = os.path.normpath(os.path.join(r"c:\Program Files\LlamaCPP\bin", os.path.basename(os.path.dirname(rel_or_abs)), os.path.basename(rel_or_abs)))
    if os.path.exists(fallback_bin):
        return fallback_bin
    return primary

def find_model_key(requested):
    if not requested:
        return next(iter(MODELS_CONFIG.keys())) if MODELS_CONFIG else None
    if "/" in requested:
        requested = requested.split("/")[-1]

    # 1. Coincidencia exacta
    if requested in MODELS_CONFIG:
        return requested

    # 2. Coincidencia sin distinción de mayúsculas/minúsculas
    req_lower = requested.strip().lower()
    for k in MODELS_CONFIG:
        if k.lower() == req_lower:
            return k

    # 3. Coincidencia por alias o nombre configurado
    for k, cfg in MODELS_CONFIG.items():
        alias = cfg.get("alias", "").lower()
        name = cfg.get("name", "").lower()
        if alias and alias == req_lower:
            return k
        if name and name == req_lower:
            return k

    # 4. Coincidencias semánticas directas
    if "bonsai" in req_lower and any(w in req_lower for w in ["ternar", "9b", "prism"]):
        if "Ternary-Bonsai-2-9B" in MODELS_CONFIG:
            return "Ternary-Bonsai-2-9B"
    if "bonsai" in req_lower and any(w in req_lower for w in ["27b", "vision"]):
        if "Bonsai-27B" in MODELS_CONFIG:
            return "Bonsai-27B"
    if "qwen2.5-7b-speculative" in req_lower and "Qwen2.5-7B-Instruct" in MODELS_CONFIG:
        return "Qwen2.5-7B-Instruct"

    # 5. Coincidencia parcial en nombres o alias
    for k, cfg in MODELS_CONFIG.items():
        if req_lower in k.lower() or (cfg.get("alias") and req_lower in cfg.get("alias").lower()):
            return k

    return None

def get_model_est_seconds(cfg, model_key):
    model_path = resolve_model_path(cfg.get("model"))
    mmproj_path = resolve_model_path(cfg.get("mmproj"))
    draft_path = resolve_model_path(cfg.get("model_draft"))

    total_bytes = 0
    for p in [model_path, mmproj_path, draft_path]:
        if p and os.path.exists(p):
            try:
                total_bytes += os.path.getsize(p)
            except Exception:
                pass

    if total_bytes > 0:
        total_gb = total_bytes / (1024 ** 3)
        est = 1.5 + (total_gb * 1.8)
        return max(3.5, round(est, 1))

    name = cfg.get("name", model_key)
    if "27B" in name or "27b" in model_key:
        return 15.0
    elif "8B" in name or "9B" in name or "8b" in model_key or "9b" in model_key:
        return 9.0
    else:
        return 6.0

def is_port_in_use(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        try:
            return s.connect_ex((host, port)) == 0
        except Exception:
            return False

def check_router_health(host="127.0.0.1", port=8080):
    try:
        url = f"http://{host}:{port}/health"
        req = urllib.request.Request(url, headers={"User-Agent": "LocalRouterLLM-Check"})
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("status") == "ok"
    except Exception:
        pass
    return False

def kill_stale_port_owner(port):
    if sys.platform != "win32":
        return
    try:
        cmd = f'powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {{ Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }}"'
        subprocess.run(cmd, shell=True, capture_output=True, timeout=5)
        time.sleep(0.4)
    except Exception:
        pass

def free_llama_port():
    try:
        subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
        time.sleep(0.3)
    except Exception:
        pass
    if is_port_in_use(LLAMA_PORT):
        kill_stale_port_owner(LLAMA_PORT)

# =========================================================
# HUD Integrado para Ventana Flotante de Carga
# =========================================================
class StandaloneHUD:
    def __init__(self, model_name="Modelo IA", est_seconds=4.0):
        self.model_name = model_name
        self.est_seconds = max(2.5, float(est_seconds))
        self.progress = 0.0
        self.target_progress = 5.0
        self.is_done = False
        self.is_failed = False
        self.is_running = True
        self.start_time = time.time()
        self.status_text = "Iniciando motor CUDA y pesos en VRAM..."

        if not HAS_TK:
            return

        try:
            self.root = tk.Tk()
        except Exception:
            return

        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#0b0f17")

        w, h = 390, 96
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(10, sw - w - 24)
        y = max(10, sh - h - 64)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        self.canvas = tk.Canvas(self.root, width=w, height=h, bg="#0b0f17", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self._draw_ui(w, h)

        self.stdin_thread = threading.Thread(target=self._listen_stdin, daemon=True)
        self.stdin_thread.start()

        self.root.after(30, self._update_loop)
        self.root.mainloop()

    def _draw_ui(self, w, h):
        self.canvas.create_rectangle(1, 1, w - 1, h - 1, outline="#00e1ff", width=2)
        self.canvas.create_rectangle(2, 2, w - 2, h - 2, outline="#0a2a40", width=1)
        self.canvas.create_rectangle(2, 2, w - 2, 4, fill="#00e1ff", outline="")
        self.canvas.create_rectangle(16, 14, 38, 36, fill="#0c2333", outline="#00e1ff", width=1)
        self.canvas.create_text(27, 25, text="⚡", font=("Segoe UI", 11), fill="#00e1ff")

        self.canvas.create_text(46, 17, text="CARGANDO EN GPU / VRAM", font=("Segoe UI", 8, "bold"), fill="#00e1ff", anchor="w")
        short_name = self.model_name if len(self.model_name) <= 32 else self.model_name[:29] + "..."
        self.canvas.create_text(46, 31, text=short_name, font=("Segoe UI", 10, "bold"), fill="#ffffff", anchor="w")

        self.bar_x1, self.bar_y1 = 16, 50
        self.bar_x2, self.bar_y2 = w - 16, 62
        self.canvas.create_rectangle(self.bar_x1, self.bar_y1, self.bar_x2, self.bar_y2, fill="#131b26", outline="#1e2d40", width=1)
        self.bar_fill_id = self.canvas.create_rectangle(self.bar_x1, self.bar_y1, self.bar_x1, self.bar_y2, fill="#00e1ff", outline="")

        self.status_id = self.canvas.create_text(16, 75, text=self.status_text, font=("Segoe UI", 8), fill="#8b9bb4", anchor="w")
        self.pct_id = self.canvas.create_text(w - 16, 75, text="0% • 0.0s", font=("Segoe UI", 8, "bold"), fill="#00e1ff", anchor="e")

    def _listen_stdin(self):
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("STATUS:"):
                    self.status_text = line[7:].strip()
                elif line.startswith("PROGRESS:"):
                    try:
                        p = float(line[9:].strip())
                        self.target_progress = max(self.target_progress, p)
                    except ValueError:
                        pass
                elif line == "READY":
                    self.is_done = True
                    break
                elif line == "FAILED":
                    self.is_failed = True
                    break
        except Exception:
            pass

    def _update_loop(self):
        if not self.root:
            return

        now = time.time()
        elapsed = now - self.start_time

        if elapsed > 90 and not self.is_done:
            self._destroy()
            return

        if not self.is_done and not self.is_failed:
            time_ratio = elapsed / self.est_seconds
            if time_ratio <= 1.0:
                time_target = 5.0 + (time_ratio * 85.0)
            else:
                overtime = elapsed - self.est_seconds
                time_target = min(95.0, 90.0 + (overtime * 0.5))

            effective_target = min(96.0, max(self.target_progress, time_target))
            diff = effective_target - self.progress
            if diff > 0:
                step = max(0.20, diff * 0.12)
                self.progress = min(self.progress + step, effective_target)

            pct_int = int(round(self.progress))
            self.canvas.itemconfig(self.pct_id, text=f"{pct_int}% • {elapsed:.1f}s")
            self.canvas.itemconfig(self.status_id, text=self.status_text)

        elif self.is_failed:
            self.canvas.itemconfig(self.pct_id, text="FALLO", fill="#ff4444")
            self.canvas.itemconfig(self.status_id, text="❌ Error al cargar modelo en VRAM", fill="#ff4444")
            self.canvas.itemconfig(self.bar_fill_id, fill="#ff4444")
            self.root.after(2000, self._destroy)
            return

        else:
            step = max(1.5, (100.0 - self.progress) * 0.35)
            self.progress = min(100.0, self.progress + step)
            pct_int = int(round(self.progress))
            self.canvas.itemconfig(self.pct_id, text=f"{pct_int}% • {elapsed:.1f}s", fill="#00ff88")
            self.canvas.itemconfig(self.status_id, text="✔ Modelo listo y activo en VRAM", fill="#00ff88")
            self.canvas.itemconfig(self.bar_fill_id, fill="#00ff88")

        total_w = self.bar_x2 - self.bar_x1
        fill_w = self.bar_x1 + (total_w * (self.progress / 100.0))
        self.canvas.coords(self.bar_fill_id, self.bar_x1, self.bar_y1, fill_w, self.bar_y2)

        if self.is_done and self.progress >= 99.8:
            self.root.after(700, self._destroy)
            return

        if self.is_running:
            self.root.after(30, self._update_loop)

    def _destroy(self):
        self.is_running = False
        try:
            self.root.destroy()
        except Exception:
            pass

class LoadingHUD:
    """Controlador que invoca el HUD en un subproceso aislado."""
    def __init__(self, model_name="Modelo IA", est_seconds=4.0):
        self.proc = None
        base_dir = BASE_DIR
        candidates = [
            os.path.join(base_dir, "hud.py"),
            os.path.join(r"c:\Program Files\LlamaCPP\LocalRouterLLM", "hud.py"),
            os.path.join(r"c:\Program Files\LlamaCPP", "hud.py")
        ]
        hud_script = None
        for c in candidates:
            if os.path.exists(c):
                hud_script = c
                break

        is_frozen = getattr(sys, "frozen", False)
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        try:
            if is_frozen:
                # Si estamos empaquetados en un ejecutable .exe, nos re-invocamos con --hud
                self.proc = subprocess.Popen(
                    [sys.executable, "--hud", model_name, str(est_seconds)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags
                )
            elif hud_script:
                py_bin = sys.executable
                if py_bin.endswith("python.exe"):
                    pyw_candidate = py_bin[:-10] + "pythonw.exe"
                    if os.path.exists(pyw_candidate):
                        py_bin = pyw_candidate
                self.proc = subprocess.Popen(
                    [py_bin, hud_script, model_name, str(est_seconds)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags
                )
        except Exception as e:
            log_warn(f"No se pudo lanzar HUD: {e}")
            self.proc = None

    def set_status(self, text):
        if self.proc and self.proc.stdin:
            try:
                msg = f"STATUS:{text}\n".encode("utf-8")
                self.proc.stdin.write(msg)
                self.proc.stdin.flush()
            except Exception:
                pass

    def set_progress(self, pct):
        if self.proc and self.proc.stdin:
            try:
                msg = f"PROGRESS:{pct:.1f}\n".encode("utf-8")
                self.proc.stdin.write(msg)
                self.proc.stdin.flush()
            except Exception:
                pass

    def update(self, status=None, progress=None):
        if progress is not None:
            self.set_progress(progress)
        if status is not None:
            self.set_status(status)

    def finish(self, success=True):
        if self.proc and self.proc.stdin:
            try:
                cmd = b"READY\n" if success else b"FAILED\n"
                self.proc.stdin.write(cmd)
                self.proc.stdin.flush()
            except Exception:
                pass

def generate_tray_image(state="idle", is_active=None, loading_angle=0):
    if is_active is not None:
        state = "active" if is_active else "idle"
    size = (64, 64)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if state == "loading":
        bg = (15, 20, 30, 250)
        border = (30, 45, 65, 200)
        draw.ellipse([3, 3, 61, 61], fill=bg, outline=border, width=2)
        draw.arc([3, 3, 61, 61], start=loading_angle, end=loading_angle + 110, fill=(0, 245, 255, 255), width=4)
        symbol_color = (0, 245, 255, 255)
        draw.line([(24, 46), (36, 18)], fill=symbol_color, width=4)
        draw.line([(31, 29), (43, 46)], fill=symbol_color, width=4)
        draw.ellipse([42, 8, 56, 22], fill=(0, 220, 255, 255), outline=(255, 255, 255, 220), width=2)
        return img
    elif state == "active":
        bg = (18, 22, 32, 255)
        border = (0, 225, 255, 255)
        draw.ellipse([3, 3, 61, 61], fill=bg, outline=border, width=3)
        symbol_color = (0, 245, 255, 255)
        draw.line([(24, 46), (36, 18)], fill=symbol_color, width=4)
        draw.line([(31, 29), (43, 46)], fill=symbol_color, width=4)
        draw.ellipse([42, 8, 56, 22], fill=(0, 255, 136, 255), outline=(255, 255, 255, 220), width=2)
        return img
    else:  # idle
        bg = (20, 22, 26, 240)
        border = (90, 100, 120, 220)
        draw.ellipse([3, 3, 61, 61], fill=bg, outline=border, width=3)
        symbol_color = (150, 165, 185, 255)
        draw.line([(24, 46), (36, 18)], fill=symbol_color, width=4)
        draw.line([(31, 29), (43, 46)], fill=symbol_color, width=4)
        draw.ellipse([42, 8, 56, 22], fill=(255, 180, 20, 255), outline=(255, 255, 255, 220), width=2)
        return img

# =========================================================
# Gestor de Modelos y Procesos en GPU
# =========================================================
class ModelManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.current_model_key = None
        self.current_process = None
        self.last_activity = time.time()
        self.tray_icon = None
        self.http_server = None
        self.is_loading = False
        self.loading_angle = 0
        self.current_hud = None
        self.last_stderr_lines = deque(maxlen=40)
        self.last_error = ""

    def set_tray_icon(self, icon):
        self.tray_icon = icon
        self.update_tray_status()

    def update_tray_status(self):
        if not self.tray_icon or not HAS_TRAY:
            return
        is_active = (self.current_model_key is not None and self.current_process is not None)
        state = "active" if is_active else "idle"
        try:
            self.tray_icon.icon = generate_tray_image(state=state)
            if is_active:
                name = MODELS_CONFIG.get(self.current_model_key, {}).get("name", self.current_model_key)
                self.tray_icon.title = f"LocalRouterLLM: Activo [{name}]"
            else:
                self.tray_icon.title = "LocalRouterLLM: En espera (VRAM libre)"
        except Exception:
            pass

    def start_loading(self, model_key, model_name, est_seconds):
        self.is_loading = True
        self.loading_angle = 0
        try:
            self.current_hud = LoadingHUD(model_name=model_name, est_seconds=est_seconds)
        except Exception:
            self.current_hud = None

        if HAS_TRAY and self.tray_icon:
            def tray_anim():
                while self.is_loading:
                    self.loading_angle = (self.loading_angle + 25) % 360
                    try:
                        self.tray_icon.icon = generate_tray_image(state="loading", loading_angle=self.loading_angle)
                        self.tray_icon.title = f"LocalRouterLLM: Cargando [{model_name}]..."
                    except Exception:
                        pass
                    time.sleep(0.08)
            threading.Thread(target=tray_anim, daemon=True).start()

    def finish_loading(self, success=True, model_name=""):
        self.is_loading = False
        if self.current_hud:
            try:
                self.current_hud.finish(success=success)
            except Exception:
                pass
            self.current_hud = None
        self.update_tray_status()

    def get_active_model(self):
        with self.lock:
            return self.current_model_key

    def touch(self):
        with self.lock:
            self.last_activity = time.time()

    def stop_current_model(self):
        if self.current_process:
            log_info(f"Deteniendo modelo ({self.current_model_key}) para liberar VRAM...")
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.current_process.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
            except Exception as e:
                log_warn(f"Error al terminar proceso: {e}")
            self.current_process = None
            self.current_model_key = None
            time.sleep(0.5)
            log_info("VRAM liberada correctamente.")
            self.update_tray_status()

    def ensure_model(self, model_key):
        with self.lock:
            self.last_activity = time.time()

            if model_key and "/" in model_key:
                model_key = model_key.split("/")[-1]

            matched_key = find_model_key(model_key)
            if model_key == "llama-server-active" or not model_key:
                if self.current_model_key and self.current_process and self.current_process.poll() is None:
                    return True
                model_key = next(iter(MODELS_CONFIG.keys())) if MODELS_CONFIG else None
            elif matched_key:
                model_key = matched_key
            else:
                default_key = next(iter(MODELS_CONFIG.keys()))
                log_info(f"Modelo '{model_key}' no encontrado, usando '{default_key}' por defecto.")
                model_key = default_key

            if self.current_model_key == model_key and self.current_process and self.current_process.poll() is None:
                return True

            if self.current_process:
                self.stop_current_model()

            # Asegurar que el puerto 8081 esté completamente libre de instancias huérfanas
            free_llama_port()

            cfg = MODELS_CONFIG[model_key]
            model_path = resolve_model_path(cfg.get("model"))
            mmproj_path = resolve_model_path(cfg.get("mmproj"))
            draft_path = resolve_model_path(cfg.get("model_draft"))

            server_exe = resolve_bin_path(cfg.get("executable")) if cfg.get("executable") else BIN_PATH
            if not os.path.exists(server_exe):
                server_exe = BIN_PATH

            if not os.path.exists(server_exe):
                self.last_error = f"No se encuentra el binario llama-server en: {server_exe}"
                log_err(self.last_error)
                return False

            if not model_path or not os.path.exists(model_path):
                self.last_error = f"No se encuentra el archivo del modelo en: {model_path}"
                log_err(self.last_error)
                return False

            model_display_name = cfg.get("name", model_key)
            est_seconds = get_model_est_seconds(cfg, model_key)
            self.start_loading(model_key, model_display_name, est_seconds)

            log_info(f"Cargando modelo: {model_display_name} | Binario: {os.path.basename(server_exe)}")
            log_info(f"Ruta GGUF: {model_path}")

            cmd = [
                server_exe,
                "--model", model_path,
                "--port", str(LLAMA_PORT),
                "--n-gpu-layers", str(cfg.get("ngl", "all")),
                "--threads", str(cfg.get("threads", 6)),
                "--threads-batch", str(cfg.get("threads_batch", 8)),
                "--fit", "off",
                "--ctx-size", str(cfg.get("ctx", 32768)),
                "--jinja",
                "--context-shift",
                "--temp", str(cfg.get("temp", 0.6)),
                "--top-p", str(cfg.get("top_p", 0.95)),
                "--top-k", str(cfg.get("top_k", 20)),
                "--min-p", str(cfg.get("min_p", 0.05)),
                "--presence-penalty", "0.0",
                "--repeat-penalty", str(cfg.get("repeat_penalty", 1.0)),
                "--parallel", "1",
                "--cache-idle-slots",
                "--alias", cfg.get("alias", model_key),
                "-lv", "4"
            ]

            if cfg.get("flash_attn", True):
                cmd.extend(["--flash-attn", "on"])
            if cfg.get("cache_type_k", "q4_0"):
                cmd.extend(["--cache-type-k", cfg.get("cache_type_k", "q4_0")])
            if cfg.get("cache_type_v", "q4_0"):
                cmd.extend(["--cache-type-v", cfg.get("cache_type_v", "q4_0")])

            if mmproj_path and os.path.exists(mmproj_path):
                cmd.extend(["--mmproj", mmproj_path, "--image-min-tokens", "1024"])

            if cfg.get("reasoning"):
                cmd.extend(["--reasoning", "on"])

            if cfg.get("cpu_moe"):
                cmd.extend(["--cpu-moe"])

            if draft_path and os.path.exists(draft_path):
                cmd.extend([
                    "--model-draft", draft_path,
                    "--spec-type", cfg.get("spec_type", "draft-mtp"),
                    "--spec-draft-n-max", str(cfg.get("spec_draft_n_max", 2)),
                    "--cache-type-k-draft", cfg.get("cache_type_k_draft", "q8_0"),
                    "--cache-type-v-draft", cfg.get("cache_type_v_draft", "q8_0")
                ])
                if "ngl_draft" in cfg:
                    cmd.extend(["--n-gpu-layers-draft", str(cfg["ngl_draft"])])
            elif cfg.get("spec_type"):
                cmd.extend([
                    "--spec-type", cfg.get("spec_type"),
                    "--spec-draft-n-max", str(cfg.get("spec_draft_n_max", 2))
                ])

            if cfg.get("no_warmup"):
                cmd.append("--no-warmup")

            startupinfo = None
            creationflags = 0
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW

            server_bin_dir = os.path.dirname(server_exe) if (server_exe and os.path.exists(server_exe)) else BIN_DIR
            self.last_stderr_lines.clear()

            self.current_process = subprocess.Popen(
                cmd,
                cwd=server_bin_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                creationflags=creationflags
            )
            self.current_model_key = model_key

            def monitor_stderr(proc, hud_ref):
                try:
                    for line in iter(proc.stderr.readline, b''):
                        if not line:
                            break
                        line_str = line.decode('utf-8', errors='ignore').strip()
                        if line_str:
                            self.last_stderr_lines.append(line_str)
                        if not hud_ref or not line_str:
                            continue

                        if 'llama_server: initializing' in line_str:
                            hud_ref.update(status="Iniciando motor CUDA y verificando GPU...", progress=10.0)
                        elif 'load_model: loading model' in line_str or 'common_params_fit' in line_str:
                            hud_ref.update(status="Accediendo a pesos GGUF y comprobando VRAM...", progress=18.0)
                        elif 'loaded meta data with' in line_str or 'llama_model_loader' in line_str:
                            hud_ref.update(status="Arquitectura y metadatos GGUF mapeados...", progress=25.0)
                        elif 'loading model tensors' in line_str:
                            hud_ref.update(status="Cargando tensores del modelo en VRAM...", progress=32.0)
                        elif 'offloaded' in line_str and 'layers' in line_str:
                            hud_ref.update(status="Capas del modelo asignadas a GPU...", progress=40.0)
                        elif 'CUDA0 model buffer size' in line_str or 'model buffer size' in line_str:
                            hud_ref.update(status="Buffers de modelo fijados en memoria GPU...", progress=85.0)
                        elif 'llama threadpool init' in line_str or 'chat template' in line_str or 'model loaded' in line_str:
                            hud_ref.update(status="Optimizando contexto KV y slots de atención...", progress=92.0)
                        elif 'listening on' in line_str:
                            hud_ref.update(status="Servidor listo en puerto local...", progress=97.0)
                except Exception:
                    pass

            threading.Thread(target=monitor_stderr, args=(self.current_process, self.current_hud), daemon=True).start()

            start_time = time.time()
            ready = False
            while time.time() - start_time < 60:
                if self.current_process.poll() is not None:
                    code = self.current_process.poll()
                    err_summary = "\n".join(list(self.last_stderr_lines)[-8:])
                    self.last_error = f"llama-server terminó con código {code}.\n{err_summary}"
                    log_err(f"llama-server terminó inesperadamente (código {code}):\n{err_summary}")
                    self.current_process = None
                    self.current_model_key = None
                    self.finish_loading(success=False, model_name=model_display_name)
                    return False
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{LLAMA_PORT}/health")
                    with urllib.request.urlopen(req, timeout=1.2) as resp:
                        if resp.status == 200:
                            ready = True
                            break
                except Exception:
                    time.sleep(0.2)

            elapsed = round(time.time() - start_time, 2)
            if ready:
                log_info(f"Modelo {model_display_name} listo y activo en {elapsed}s.")
                self.finish_loading(success=True, model_name=model_display_name)
                return True
            else:
                err_summary = "\n".join(list(self.last_stderr_lines)[-8:])
                self.last_error = f"Tiempo de espera agotado esperando a llama-server.\n{err_summary}"
                log_err(self.last_error)
                self.finish_loading(success=False, model_name=model_display_name)
                self.stop_current_model()
                return False

    def idle_checker_loop(self):
        while True:
            time.sleep(15)
            with self.lock:
                if self.current_process and self.current_process.poll() is None:
                    idle_time = time.time() - self.last_activity
                    if idle_time > IDLE_TIMEOUT_SECONDS:
                        mins = int(idle_time // 60)
                        log_info(f"Inactividad de {mins} minutos detectada. Auto-descargando modelo...")
                        self.stop_current_model()

manager = ModelManager()

# =========================================================
# Web Dashboard HTML Template
# =========================================================
def get_dashboard_html():
    active = manager.get_active_model()
    is_active = (active is not None and manager.current_process is not None)
    status_label = f"Activo: {MODELS_CONFIG.get(active, {}).get('name', active)}" if is_active else "En espera (0% VRAM)"
    badge_class = "active" if is_active else "idle"

    models_html = []
    for k, cfg in MODELS_CONFIG.items():
        name = cfg.get("name", k)
        ctx = cfg.get("ctx", 32768)
        ctx_k = f"{ctx // 1024}K"
        is_cur = (k == active and is_active)
        cur_badge = '<span class="badge cur">EN GPU</span>' if is_cur else ''

        tags = [f'<span class="tag ctx">{ctx_k} Context</span>']
        if cfg.get("mmproj"):
            tags.append('<span class="tag vision">👁️ Vision</span>')
        if cfg.get("spec_type") or cfg.get("model_draft"):
            tags.append('<span class="tag mtp">⚡ MTP Draft</span>')
        if cfg.get("reasoning"):
            tags.append('<span class="tag reason">🧠 Reasoning</span>')

        tags_html = " ".join(tags)
        card_class = "model-card active-card" if is_cur else "model-card"

        models_html.append(f"""
        <div class="{card_class}">
            <div class="card-head">
                <span class="card-title">{name}</span>
                {cur_badge}
            </div>
            <div class="card-tags">{tags_html}</div>
            <div class="card-actions">
                <button class="btn btn-sm" onclick="loadModel('{k}')">🚀 Cargar en GPU</button>
            </div>
        </div>
        """)

    cards_rendered = "\n".join(models_html)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LocalRouterLLM - Panel de Control</title>
    <style>
        :root {{
            --bg: #090d16;
            --surface: #101726;
            --surface-hover: #162034;
            --border: #1e293b;
            --cyan: #00e1ff;
            --green: #00ff88;
            --amber: #ffb800;
            --red: #ff4444;
            --text: #f1f5f9;
            --text-dim: #94a3b8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif; }}
        body {{ background: var(--bg); color: var(--text); padding: 24px; min-height: 100vh; }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 20px; margin-bottom: 24px; }}
        .brand {{ display: flex; align-items: center; gap: 14px; }}
        .brand-icon {{ font-size: 28px; width: 48px; height: 48px; background: #0c2333; border: 1px solid var(--cyan); border-radius: 12px; display: flex; align-items: center; justify-content: center; box-shadow: 0 0 15px rgba(0,225,255,0.25); }}
        .brand-title {{ font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }}
        .brand-subtitle {{ font-size: 13px; color: var(--text-dim); margin-top: 2px; }}
        .status-badge {{ display: inline-flex; align-items: center; gap: 8px; padding: 8px 16px; border-radius: 30px; font-size: 13px; font-weight: 600; border: 1px solid transparent; }}
        .status-badge.active {{ background: rgba(0,255,136,0.12); border-color: var(--green); color: var(--green); }}
        .status-badge.idle {{ background: rgba(255,184,0,0.12); border-color: var(--amber); color: var(--amber); }}
        .status-badge.loading {{ background: rgba(0,225,255,0.12); border-color: var(--cyan); color: var(--cyan); }}
        .dot {{ width: 8px; height: 8px; border-radius: 50%; background: currentColor; display: inline-block; animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0% {{ opacity: 1; }} 50% {{ opacity: 0.3; }} 100% {{ opacity: 1; }} }}
        .controls {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 28px; }}
        .btn {{ background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 12px 18px; border-radius: 10px; font-weight: 600; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; justify-content: center; gap: 8px; text-decoration: none; }}
        .btn:hover {{ background: var(--surface-hover); border-color: var(--cyan); color: var(--cyan); transform: translateY(-1px); }}
        .btn-cyan {{ background: #0c2333; border-color: var(--cyan); color: var(--cyan); }}
        .btn-green {{ background: #0c2d20; border-color: var(--green); color: var(--green); }}
        .btn-red {{ background: #2d0c0c; border-color: var(--red); color: var(--red); }}
        .btn-sm {{ padding: 6px 12px; font-size: 12px; border-radius: 6px; }}
        .section-title {{ font-size: 16px; font-weight: 700; margin-bottom: 14px; display: flex; align-items: center; justify-content: space-between; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; margin-bottom: 30px; }}
        .model-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px; transition: all 0.2s; display: flex; flex-direction: column; justify-content: space-between; }}
        .model-card:hover {{ border-color: #38bdf8; transform: translateY(-2px); }}
        .model-card.active-card {{ border-color: var(--green); box-shadow: 0 0 15px rgba(0,255,136,0.15); }}
        .card-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin-bottom: 10px; }}
        .card-title {{ font-size: 14px; font-weight: 700; color: #fff; line-height: 1.3; }}
        .card-tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }}
        .tag {{ font-size: 11px; padding: 3px 8px; border-radius: 6px; font-weight: 600; }}
        .tag.ctx {{ background: #1e293b; color: #94a3b8; }}
        .tag.vision {{ background: #2e1065; color: #c084fc; border: 1px solid #7c3aed; }}
        .tag.mtp {{ background: #083344; color: #22d3ee; border: 1px solid #0891b2; }}
        .tag.reason {{ background: #451a03; color: #fb923c; border: 1px solid #c2410c; }}
        .badge.cur {{ background: var(--green); color: #000; font-size: 10px; font-weight: 800; padding: 3px 7px; border-radius: 4px; }}
        .info-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px; margin-bottom: 24px; font-size: 13px; line-height: 1.6; }}
        .code {{ background: #050811; border: 1px solid #1e293b; padding: 2px 6px; border-radius: 4px; color: var(--cyan); font-family: monospace; }}
        .toast {{ position: fixed; bottom: 20px; right: 20px; background: #0c2333; border: 1px solid var(--cyan); color: var(--text); padding: 12px 20px; border-radius: 8px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); display: none; z-index: 1000; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="brand">
                <div class="brand-icon">⚡</div>
                <div>
                    <div class="brand-title">LocalRouterLLM v1.2.1</div>
                    <div class="brand-subtitle">Smart On-Demand Model Router & VRAM Manager para Llama.cpp</div>
                </div>
            </div>
            <div id="statusBadge" class="status-badge {badge_class}">
                <span class="dot"></span>
                <span id="statusText">{status_label}</span>
            </div>
        </header>

        <div class="controls">
            <button class="btn btn-red" onclick="releaseVRAM()">⚡ Liberar VRAM Ahora</button>
            <button class="btn btn-cyan" onclick="openOpenCode()">💻 Abrir OpenCode</button>
            <button class="btn" onclick="copyAPI()">📋 Copiar Endpoint URL</button>
            <button class="btn" onclick="window.location.reload()">🔄 Actualizar</button>
        </div>

        <div class="info-box">
            <strong>🔌 Integración OpenAI Compatible:</strong> Conecta OpenCode, Continue.dev, Cline o Aider a <span class="code">http://127.0.0.1:8080/v1</span> (API Key: <span class="code">local</span>).
            Los modelos se cargarán dinámicamente en GPU según la petición y se auto-descargarán tras {IDLE_TIMEOUT_SECONDS // 60} minutos de inactividad manteniendo tu GPU fresca y VRAM 100% libre.
        </div>

        <div class="section-title">
            <span>Catálogo de Modelos Disponibles ({len(MODELS_CONFIG)})</span>
            <span style="font-size:12px; color:var(--text-dim);">Haz clic en "Cargar en GPU" para probar cualquier modelo</span>
        </div>

        <div class="grid">
            {cards_rendered}
        </div>
    </div>

    <div id="toast" class="toast"></div>

    <script>
        function showToast(msg) {{
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.style.display = 'block';
            setTimeout(() => {{ t.style.display = 'none'; }}, 3000);
        }}

        async function releaseVRAM() {{
            showToast('Liberando VRAM...');
            try {{
                const res = await fetch('/api/vram/release', {{ method: 'POST' }});
                const data = await res.json();
                showToast(data.message || 'VRAM liberada correctamente');
                setTimeout(() => window.location.reload(), 1000);
            }} catch(e) {{
                showToast('Error al liberar VRAM');
            }}
        }}

        async function openOpenCode() {{
            showToast('Lanzando OpenCode...');
            try {{
                await fetch('/api/opencode', {{ method: 'POST' }});
            }} catch(e) {{}}
        }}

        async function loadModel(key) {{
            showToast('Iniciando carga de ' + key + ' en VRAM...');
            try {{
                const res = await fetch('/api/models/load?model=' + encodeURIComponent(key), {{ method: 'POST' }});
                const data = await res.json();
                if (data.status === 'ok') {{
                    showToast('¡Modelo ' + key + ' listo en VRAM!');
                    setTimeout(() => window.location.reload(), 800);
                }} else {{
                    showToast('Error: ' + (data.error || 'Fallo de carga'));
                }}
            }} catch(e) {{
                showToast('Error de conexión con el router');
            }}
        }}

        function copyAPI() {{
            navigator.clipboard.writeText('http://127.0.0.1:8080/v1');
            showToast('¡Copiado: http://127.0.0.1:8080/v1!');
        }}

        // Polling de salud cada 3 segundos
        setInterval(async () => {{
            try {{
                const res = await fetch('/health');
                const data = await res.json();
                const badge = document.getElementById('statusBadge');
                const text = document.getElementById('statusText');
                if (data.active_model) {{
                    badge.className = 'status-badge active';
                    text.innerText = 'Activo: ' + data.active_model;
                }} else {{
                    badge.className = 'status-badge idle';
                    text.innerText = 'En espera (0% VRAM)';
                }}
            }} catch(e) {{}}
        }}, 3000);
    </script>
</body>
</html>
"""

# =========================================================
# Manejador HTTP del Router y Proxy
# =========================================================
def launch_opencode():
    subprocess.Popen("cmd /c start opencode", shell=True)

class RouterHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path

        # 1. Panel de Control Web
        if path in ["/", "/dashboard", "/status"]:
            html = get_dashboard_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        # 2. Si se navega a /v1 en un navegador web
        if path == "/v1":
            accept = self.headers.get("Accept", "")
            if "text/html" in accept:
                html = get_dashboard_html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return

        # 3. Modelos OpenAI
        if path in ["/v1/models", "/models"]:
            manager.touch()
            models_list = []
            for m_id, m_data in MODELS_CONFIG.items():
                models_list.append({
                    "id": m_id,
                    "object": "model",
                    "created": int(START_TIME),
                    "owned_by": "local-router-llm",
                    "name": m_data.get("name", m_id)
                })
            models_list.append({
                "id": "llama-server-active",
                "object": "model",
                "created": int(START_TIME),
                "owned_by": "local-router-llm",
                "name": "LocalRouterLLM - Servidor Activo"
            })
            resp_payload = {
                "object": "list",
                "data": models_list
            }
            body = json.dumps(resp_payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 4. Salud del Router
        if path in ["/health", "/v1/health"]:
            active = manager.get_active_model()
            uptime = int(time.time() - START_TIME)
            resp = json.dumps({
                "status": "ok",
                "active_model": active,
                "uptime_seconds": uptime,
                "models_count": len(MODELS_CONFIG)
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        # 5. APIs Auxiliares
        if path == "/api/vram/release":
            manager.stop_current_model()
            resp = json.dumps({"status": "ok", "message": "VRAM y memoria GPU liberadas al 100%"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        if path == "/api/opencode":
            launch_opencode()
            resp = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        if path == "/api/logs":
            log_content = ""
            if os.path.exists(LOG_PATH):
                try:
                    with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        log_content = "".join(lines[-40:])
                except Exception:
                    pass
            body = log_content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/models/load":
            query = urllib.parse.parse_qs(url_parts.query)
            target = query.get("model", [None])[0]
            if target:
                ok = manager.ensure_model(target)
                status_code = 200 if ok else 500
                resp = json.dumps({"status": "ok" if ok else "error", "error": manager.last_error}).encode("utf-8")
            else:
                status_code = 400
                resp = json.dumps({"status": "error", "error": "Falta parámetro 'model'"}).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        # 6. Proxy a llama-server para endpoints GET restantes
        self.proxy_request("GET")

    def do_POST(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path

        if path == "/api/vram/release":
            manager.stop_current_model()
            resp = json.dumps({"status": "ok", "message": "VRAM y memoria GPU liberadas al 100%"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        if path == "/api/opencode":
            launch_opencode()
            resp = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        if path == "/api/models/load":
            query = urllib.parse.parse_qs(url_parts.query)
            target = query.get("model", [None])[0]
            if not target:
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length > 0:
                    try:
                        b = json.loads(self.rfile.read(content_length).decode("utf-8"))
                        target = b.get("model")
                    except Exception:
                        pass
            if target:
                ok = manager.ensure_model(target)
                status_code = 200 if ok else 500
                resp = json.dumps({"status": "ok" if ok else "error", "error": manager.last_error}).encode("utf-8")
            else:
                status_code = 400
                resp = json.dumps({"status": "error", "error": "Falta parámetro 'model'"}).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b""

        requested_model = None
        if post_data:
            try:
                body_json = json.loads(post_data.decode("utf-8"))
                requested_model = body_json.get("model")
            except Exception:
                pass

        if requested_model and "/" in requested_model:
            requested_model = requested_model.split("/")[-1]

        if not requested_model:
            requested_model = manager.get_active_model() or next(iter(MODELS_CONFIG.keys()))

        ok = manager.ensure_model(requested_model)
        if not ok:
            err_msg = json.dumps({
                "error": {
                    "message": f"No se pudo cargar el modelo '{requested_model}'.",
                    "details": manager.last_error
                }
            }).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_msg)))
            self.end_headers()
            self.wfile.write(err_msg)
            return

        manager.touch()
        self.proxy_request("POST", post_data)

    def proxy_request(self, method, data=None):
        target_url = f"http://127.0.0.1:{LLAMA_PORT}{self.path}"
        headers = {}
        for h, v in self.headers.items():
            if h.lower() not in ["host", "content-length"]:
                headers[h] = v
        headers["Host"] = f"127.0.0.1:{LLAMA_PORT}"

        req = urllib.request.Request(target_url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                self.send_response(resp.status)
                for h, v in resp.getheaders():
                    if h.lower() not in ["connection", "transfer-encoding", "content-length"]:
                        self.send_header(h, v)
                self.send_header("Connection", "close")
                self.end_headers()

                while True:
                    chunk = resp.read(2048)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            # Si no hay modelo activo aún o llama-server no responde
            active = manager.get_active_model()
            msg = str(e)
            if not active:
                msg = "Ningún modelo cargado en GPU en este momento. Envía una consulta a /v1/chat/completions para cargar uno automáticamente."
            err = json.dumps({"error": {"message": msg, "target": target_url}}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)

# =========================================================
# Menú y Manejo de la Bandeja del Sistema (System Tray)
# =========================================================
def action_open_dashboard(icon=None, item=None):
    webbrowser.open(f"http://{ROUTER_HOST}:{ROUTER_PORT}/")

def action_release_vram(icon=None, item=None):
    manager.stop_current_model()

def action_open_opencode(icon=None, item=None):
    launch_opencode()

def action_open_logs(icon=None, item=None):
    if os.path.exists(LOG_PATH):
        try:
            os.startfile(LOG_PATH)
        except Exception:
            pass

def action_open_config_dir(icon=None, item=None):
    try:
        os.startfile(BASE_DIR)
    except Exception:
        pass

def action_quit(icon=None, item=None):
    log_info("Cerrando router y liberando memoria...")
    manager.finish_loading(success=False)
    manager.stop_current_model()
    if icon:
        try:
            icon.stop()
        except Exception:
            pass
    if manager.http_server:
        threading.Thread(target=manager.http_server.shutdown, daemon=True).start()

def get_menu_status_text(item):
    active = manager.get_active_model()
    if active:
        name = MODELS_CONFIG.get(active, {}).get("name", active)
        return f"📌 Activo: {name}"
    return "📌 Estado: En espera (VRAM libre)"

def build_tray_menu():
    return pystray.Menu(
        pystray.MenuItem(get_menu_status_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("🌐 Abrir Panel Web", action_open_dashboard, default=True),
        pystray.MenuItem("⚡ Liberar VRAM ahora", action_release_vram),
        pystray.MenuItem("💻 Abrir OpenCode", action_open_opencode),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("📋 Ver Registro (router.log)", action_open_logs),
        pystray.MenuItem("📂 Abrir Carpeta LocalRouter", action_open_config_dir),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ Salir de LocalRouterLLM", action_quit)
    )

# =========================================================
# Servidor Principal
# =========================================================
def run_server():
    # 1. Comprobar si ya existe una instancia activa y respondiendo
    if check_router_health(ROUTER_HOST, ROUTER_PORT):
        log_info(f"LocalRouterLLM ya está ejecutándose en http://{ROUTER_HOST}:{ROUTER_PORT}.")
        log_info("Abriendo panel web en el navegador...")
        webbrowser.open(f"http://{ROUTER_HOST}:{ROUTER_PORT}/")
        sys.exit(0)

    # 2. Si el puerto 8080 está ocupado pero no responde a /health, limpiar proceso zombi
    if is_port_in_use(ROUTER_PORT, ROUTER_HOST):
        log_warn(f"El puerto {ROUTER_PORT} está ocupado por un proceso inactivo. Liberando...")
        kill_stale_port_owner(ROUTER_PORT)
        time.sleep(0.5)

    # 3. Limpiar cualquier servidor llama-server en puerto 8081
    free_llama_port()

    idle_thread = threading.Thread(target=manager.idle_checker_loop, daemon=True)
    idle_thread.start()

    HTTPServer.allow_reuse_address = True
    server_address = (ROUTER_HOST, ROUTER_PORT)
    try:
        httpd = HTTPServer(server_address, RouterHandler)
    except OSError as e:
        log_err(f"No se pudo enlazar al puerto {ROUTER_PORT}: {e}")
        # Intentar una última limpieza de puerto
        kill_stale_port_owner(ROUTER_PORT)
        time.sleep(1)
        httpd = HTTPServer(server_address, RouterHandler)

    manager.http_server = httpd

    tray_icon = None
    if HAS_TRAY:
        try:
            initial_img = generate_tray_image(state="idle")
            tray_icon = pystray.Icon(
                "LocalRouterLLM",
                initial_img,
                "LocalRouterLLM: En espera",
                menu=build_tray_menu()
            )
            manager.set_tray_icon(tray_icon)
            tray_icon.run_detached()
        except Exception as e:
            log_warn(f"No se pudo inicializar icono en la bandeja: {e}")
            tray_icon = None

    log_info("=======================================================")
    log_info(" LocalRouterLLM v1.2.1 - Smart On-Demand Model Router")
    log_info(f" Servidor escuchando en: http://{ROUTER_HOST}:{ROUTER_PORT}/v1")
    log_info(f" Panel Web de Control:  http://{ROUTER_HOST}:{ROUTER_PORT}/")
    log_info(f" Tiempo de inactividad para descarga: {IDLE_TIMEOUT_SECONDS // 60} minutos")
    if HAS_TRAY and tray_icon:
        log_info(" [Bandeja] Icono activo en la barra de tareas (junto al reloj).")
    log_info("=======================================================")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        log_info("Cerrando servidor y liberando memoria...")
        manager.finish_loading(success=False)
        manager.stop_current_model()
        if tray_icon:
            try:
                tray_icon.stop()
            except Exception:
                pass
        try:
            httpd.server_close()
        except Exception:
            pass
        log_info("Apagado completo de LocalRouterLLM.")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--hud":
        model = sys.argv[2] if len(sys.argv) > 2 else "Modelo IA"
        duration = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0
        StandaloneHUD(model_name=model, est_seconds=duration)
    else:
        run_server()
