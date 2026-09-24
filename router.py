"""
LocalRouterLLM
==============
Smart On-Demand Model Router & VRAM Manager for Llama.cpp and Local AI Agents.
- Compatible with OpenCode, Continue.dev, Aider, Cline, and any OpenAI API client.
- Dynamic single-model VRAM management (0% VRAM when idle).
- Configurable auto-unload timer.
- Interactive Windows System Tray icon with 1-click VRAM flush.
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

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
EXAMPLE_CONFIG_PATH = os.path.join(BASE_DIR, "config.example.json")

def load_config():
    path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else EXAMPLE_CONFIG_PATH
    if not os.path.exists(path):
        print(f"[Error] No se encontró archivo de configuración en {path}")
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

# Resolver rutas relativas
BIN_PATH = os.path.abspath(os.path.join(BASE_DIR, LLAMA_CFG.get("executable", "llama-server.exe")))
BIN_DIR = os.path.dirname(BIN_PATH)
MODELS_DIR = os.path.abspath(os.path.join(BASE_DIR, LLAMA_CFG.get("models_dir", "../gguf")))

def resolve_model_path(rel_or_abs):
    if not rel_or_abs:
        return None
    if os.path.isabs(rel_or_abs):
        return rel_or_abs
    return os.path.normpath(os.path.join(MODELS_DIR, rel_or_abs))

def generate_tray_image(is_active=False):
    size = (64, 64)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg = (18, 22, 32, 255) if is_active else (20, 22, 26, 240)
    border = (0, 225, 255, 255) if is_active else (90, 100, 120, 220)
    draw.ellipse([3, 3, 61, 61], fill=bg, outline=border, width=3)

    symbol_color = (0, 245, 255, 255) if is_active else (150, 165, 185, 255)
    draw.line([(24, 46), (36, 18)], fill=symbol_color, width=4)
    draw.line([(31, 29), (43, 46)], fill=symbol_color, width=4)

    dot_fill = (0, 255, 136, 255) if is_active else (255, 180, 20, 255)
    draw.ellipse([42, 8, 56, 22], fill=dot_fill, outline=(255, 255, 255, 220), width=2)
    return img

class ModelManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.current_model_key = None
        self.current_process = None
        self.last_activity = time.time()
        self.tray_icon = None
        self.http_server = None

    def set_tray_icon(self, icon):
        self.tray_icon = icon
        self.update_tray_status()

    def update_tray_status(self):
        if not self.tray_icon or not HAS_TRAY:
            return
        is_active = (self.current_model_key is not None and self.current_process is not None)
        try:
            self.tray_icon.icon = generate_tray_image(is_active)
            if is_active:
                name = MODELS_CONFIG.get(self.current_model_key, {}).get("name", self.current_model_key)
                self.tray_icon.title = f"LocalRouterLLM: Activo [{name}]"
            else:
                self.tray_icon.title = "LocalRouterLLM: En espera (VRAM libre)"
        except Exception:
            pass

    def get_active_model(self):
        with self.lock:
            return self.current_model_key

    def touch(self):
        with self.lock:
            self.last_activity = time.time()

    def stop_current_model(self):
        if self.current_process:
            print(f"[Router] Deteniendo modelo ({self.current_model_key}) para liberar VRAM...")
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.current_process.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                print(f"[Router] Error al terminar proceso: {e}")
            self.current_process = None
            self.current_model_key = None
            time.sleep(1.0)
            print("[Router] VRAM liberada correctamente.")
            self.update_tray_status()

    def ensure_model(self, model_key):
        with self.lock:
            self.last_activity = time.time()

            if model_key == "llama-server-active" or not model_key:
                if self.current_model_key and self.current_process and self.current_process.poll() is None:
                    return True
                model_key = next(iter(MODELS_CONFIG.keys())) if MODELS_CONFIG else None

            if not model_key or model_key not in MODELS_CONFIG:
                default_key = next(iter(MODELS_CONFIG.keys()))
                print(f"[Router] Modelo '{model_key}' no encontrado, usando '{default_key}' por defecto.")
                model_key = default_key

            if self.current_model_key == model_key and self.current_process and self.current_process.poll() is None:
                return True

            if self.current_process:
                self.stop_current_model()

            cfg = MODELS_CONFIG[model_key]
            model_path = resolve_model_path(cfg.get("model"))
            mmproj_path = resolve_model_path(cfg.get("mmproj"))
            draft_path = resolve_model_path(cfg.get("model_draft"))

            if not os.path.exists(BIN_PATH):
                print(f"[Router ERROR] No se encuentra el binario llama-server en: {BIN_PATH}")
                return False

            if not os.path.exists(model_path):
                print(f"[Router ERROR] No se encuentra el archivo del modelo en: {model_path}")
                return False

            print("=======================================================")
            print(f"[Router] Cargando modelo: {cfg.get('name', model_key)}")
            print(f"[Router] Ruta GGUF: {model_path}")
            print("=======================================================")

            cmd = [
                BIN_PATH,
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
                "--alias", cfg.get("alias", model_key)
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

            self.current_process = subprocess.Popen(
                cmd,
                cwd=BIN_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.current_model_key = model_key
            self.update_tray_status()

            start_time = time.time()
            ready = False
            while time.time() - start_time < 60:
                if self.current_process.poll() is not None:
                    print(f"[Router ERROR] llama-server terminó inesperadamente (código {self.current_process.poll()}).")
                    self.current_process = None
                    self.current_model_key = None
                    self.update_tray_status()
                    return False
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{LLAMA_PORT}/health")
                    with urllib.request.urlopen(req, timeout=1.5) as resp:
                        if resp.status == 200:
                            ready = True
                            break
                except Exception:
                    time.sleep(0.3)

            elapsed = round(time.time() - start_time, 2)
            if ready:
                print(f"[Router] Modelo listo y activo en {elapsed}s.")
                self.update_tray_status()
                return True
            else:
                print("[Router ERROR] Tiempo de espera agotado esperando a llama-server.")
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
                        print(f"[Router] Inactividad de {mins} minutos detectada. Auto-descargando modelo...")
                        self.stop_current_model()

manager = ModelManager()

class RouterHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ["/v1/models", "/models"]:
            manager.touch()
            models_list = []
            for m_id, m_data in MODELS_CONFIG.items():
                models_list.append({
                    "id": m_id,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "local-router-llm",
                    "name": m_data.get("name", m_id)
                })
            models_list.append({
                "id": "llama-server-active",
                "object": "model",
                "created": int(time.time()),
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

        if path in ["/health", "/v1/health"]:
            active = manager.get_active_model()
            resp = json.dumps({"status": "ok", "active_model": active}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        self.proxy_request("GET")

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b""

        requested_model = None
        if post_data:
            try:
                body_json = json.loads(post_data.decode("utf-8"))
                requested_model = body_json.get("model")
            except Exception:
                pass

        if not requested_model:
            requested_model = manager.get_active_model() or next(iter(MODELS_CONFIG.keys()))

        ok = manager.ensure_model(requested_model)
        if not ok:
            err_msg = json.dumps({"error": {"message": f"No se pudo cargar el modelo '{requested_model}'."}}).encode("utf-8")
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
            err = json.dumps({"error": {"message": str(e)}}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)

def launch_opencode():
    subprocess.Popen("cmd /c start opencode", shell=True)

def action_release_vram(icon, item):
    manager.stop_current_model()

def action_open_opencode(icon, item):
    launch_opencode()

def action_quit(icon, item):
    print("\n[Router] Cerrando router y liberando memoria...")
    manager.stop_current_model()
    if icon:
        icon.stop()
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
        pystray.MenuItem("⚡ Liberar VRAM ahora", action_release_vram),
        pystray.MenuItem("💻 Abrir OpenCode", action_open_opencode),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ Salir de LocalRouterLLM", action_quit)
    )

def run_server():
    idle_thread = threading.Thread(target=manager.idle_checker_loop, daemon=True)
    idle_thread.start()

    server_address = (ROUTER_HOST, ROUTER_PORT)
    httpd = HTTPServer(server_address, RouterHandler)
    manager.http_server = httpd

    tray_icon = None
    if HAS_TRAY:
        initial_img = generate_tray_image(is_active=False)
        tray_icon = pystray.Icon(
            "LocalRouterLLM",
            initial_img,
            "LocalRouterLLM: En espera",
            menu=build_tray_menu()
        )
        manager.set_tray_icon(tray_icon)
        tray_icon.run_detached()

    print("=======================================================")
    print(" LocalRouterLLM - Smart On-Demand Model Router")
    print(f" Servidor escuchando en: http://{ROUTER_HOST}:{ROUTER_PORT}/v1")
    print(f" Tiempo de inactividad para descarga: {IDLE_TIMEOUT_SECONDS // 60} minutos")
    if HAS_TRAY:
        print(" [Bandeja] Icono activo en la barra de tareas (junto al reloj).")
    print("=======================================================")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[Router] Cerrando servidor y liberando memoria...")
        manager.stop_current_model()
        if tray_icon:
            tray_icon.stop()
        httpd.server_close()
        print("[Router] Apagado completo.")

if __name__ == "__main__":
    run_server()
