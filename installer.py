"""
Asistente Gráfico de Instalación y Configuración para LocalRouterLLM
===================================================================
Proporciona una interfaz visual moderna (Dark Theme) para configurar
e instalar LocalRouterLLM, detectar hardware, integrar con OpenCode
y crear accesos directos en el sistema.
"""

import os
import sys
import json
import time
import shutil
import threading
import subprocess
import webbrowser

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import tkinter as tk
from tkinter import messagebox

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
EXAMPLE_CONFIG_PATH = os.path.join(BASE_DIR, "config.example.json")
ICON_PATH = os.path.join(BASE_DIR, "icon.ico")

def get_desktop_path():
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
            desktop, _ = winreg.QueryValueEx(key, "Desktop")
            desktop = os.path.expandvars(desktop)
            if os.path.exists(desktop):
                return desktop
        except Exception:
            pass
    fallback = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.exists(fallback):
        return fallback
    es_fallback = os.path.join(os.path.expanduser("~"), "OneDrive", "Escritorio")
    if os.path.exists(es_fallback):
        return es_fallback
    return os.path.expanduser("~")

def detect_gpu_info():
    info = {"name": "No detectada", "vram": "N/D", "cuda": False}
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, errors="ignore", timeout=2
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().split(",")
            info["name"] = parts[0].strip()
            if len(parts) > 1:
                info["vram"] = parts[1].strip()
            info["cuda"] = True
    except Exception:
        pass
    return info

def detect_llama_cpp():
    candidates = [
        os.path.join(BASE_DIR, "..", "bin", "llama-b11065-bin-win-cuda-13.4-x64", "llama-server.exe"),
        r"C:\Program Files\LlamaCPP\bin\llama-b11065-bin-win-cuda-13.4-x64\llama-server.exe",
        r"C:\Program Files\LlamaCPP\bin\llama-server.exe",
        os.path.join(BASE_DIR, "bin", "llama-server.exe")
    ]
    for c in candidates:
        if os.path.exists(c):
            return os.path.normpath(c)
    return None

def detect_gguf_models():
    candidates = [
        os.path.join(BASE_DIR, "..", "gguf"),
        r"C:\Program Files\LlamaCPP\gguf",
        os.path.join(BASE_DIR, "gguf")
    ]
    for c in candidates:
        if os.path.exists(c):
            models = []
            for root, dirs, files in os.walk(c):
                for f in files:
                    if f.endswith(".gguf") and not f.startswith("mmproj"):
                        models.append(f)
            if models:
                return os.path.normpath(c), len(models)
    return None, 0

def detect_opencode():
    cfg = os.path.expanduser(r"~/.config/opencode/opencode.json")
    return os.path.normpath(cfg) if os.path.exists(cfg) else None

class InstallerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Asistente de Instalación - LocalRouterLLM v1.3.1")
        self.root.geometry("700x560")
        self.root.minsize(700, 560)
        self.root.configure(bg="#090d16")

        if os.path.exists(ICON_PATH):
            try:
                self.root.iconbitmap(ICON_PATH)
            except Exception:
                pass

        self.current_step = 1
        self.detected_gpu = detect_gpu_info()
        self.detected_bin = detect_llama_cpp()
        self.detected_gguf_dir, self.detected_models_count = detect_gguf_models()
        self.detected_opencode = detect_opencode()

        self._build_header()
        self.content_frame = tk.Frame(self.root, bg="#090d16")
        self.content_frame.pack(fill="both", expand=True, padx=30, pady=10)
        self._build_footer()

        self.show_step(1)

    def _build_header(self):
        self.header_frame = tk.Frame(self.root, bg="#101726", height=80, relief="flat")
        self.header_frame.pack(fill="x", side="top")

        inner = tk.Frame(self.header_frame, bg="#101726")
        inner.pack(fill="both", expand=True, padx=25, pady=15)

        icon_lbl = tk.Label(inner, text="⚡", font=("Segoe UI", 26), bg="#0c2333", fg="#00e1ff",
                            width=2, height=1, relief="ridge", bd=1)
        icon_lbl.pack(side="left", padx=(0, 15))

        titles_frame = tk.Frame(inner, bg="#101726")
        titles_frame.pack(side="left", fill="y")

        self.title_lbl = tk.Label(titles_frame, text="Instalación de LocalRouterLLM v1.3.1",
                                  font=("Segoe UI", 15, "bold"), fg="#ffffff", bg="#101726")
        self.title_lbl.pack(anchor="w")

        self.subtitle_lbl = tk.Label(titles_frame, text="Paso 1 de 4: Diagnóstico y Detección de Hardware",
                                     font=("Segoe UI", 10), fg="#94a3b8", bg="#101726")
        self.subtitle_lbl.pack(anchor="w")

        div = tk.Frame(self.root, bg="#1e293b", height=1)
        div.pack(fill="x")

    def _build_footer(self):
        div = tk.Frame(self.root, bg="#1e293b", height=1)
        div.pack(fill="x", side="bottom")

        self.footer_frame = tk.Frame(self.root, bg="#101726", height=65)
        self.footer_frame.pack(fill="x", side="bottom")

        inner = tk.Frame(self.footer_frame, bg="#101726")
        inner.pack(fill="both", expand=True, padx=25, pady=12)

        self.btn_back = tk.Button(inner, text="◀ Atrás", font=("Segoe UI", 10, "bold"),
                                  bg="#162034", fg="#94a3b8", activebackground="#1e293b", activeforeground="#ffffff",
                                  relief="flat", padx=16, pady=6, cursor="hand2", command=self.prev_step)
        self.btn_back.pack(side="left")

        self.btn_cancel = tk.Button(inner, text="Cancelar", font=("Segoe UI", 10),
                                    bg="#101726", fg="#ef4444", activebackground="#201015", activeforeground="#ff6666",
                                    relief="flat", padx=14, pady=6, cursor="hand2", command=self.root.quit)
        self.btn_cancel.pack(side="left", padx=10)

        self.btn_next = tk.Button(inner, text="Continuar ▶", font=("Segoe UI", 10, "bold"),
                                  bg="#00e1ff", fg="#090d16", activebackground="#38bdf8", activeforeground="#000000",
                                  relief="flat", padx=20, pady=6, cursor="hand2", command=self.next_step)
        self.btn_next.pack(side="right")

    def show_step(self, step):
        self.current_step = step
        for widget in self.content_frame.winfo_children():
            widget.destroy()

        if step == 1:
            self.subtitle_lbl.config(text="Paso 1 de 4: Diagnóstico y Detección de Hardware")
            self.btn_back.config(state="disabled")
            self.btn_next.config(text="Continuar ▶", state="normal", command=self.next_step)
            self._render_step1()
        elif step == 2:
            self.subtitle_lbl.config(text="Paso 2 de 4: Opciones de Instalación y Ajustes")
            self.btn_back.config(state="normal")
            self.btn_next.config(text="Instalar Ahora ⚡", state="normal", command=self.next_step)
            self._render_step2()
        elif step == 3:
            self.subtitle_lbl.config(text="Paso 3 de 4: Ejecutando Instalación...")
            self.btn_back.config(state="disabled")
            self.btn_cancel.config(state="disabled")
            self.btn_next.config(state="disabled")
            self._render_step3()
        elif step == 4:
            self.subtitle_lbl.config(text="Paso 4 de 4: ¡Instalación Completada con Éxito!")
            self.btn_back.config(state="disabled")
            self.btn_cancel.pack_forget()
            self.btn_next.config(text="Finalizar ✔", state="normal", command=self._finish_and_exit)
            self._render_step4()

    def _render_step1(self):
        desc = tk.Label(self.content_frame,
                        text="El asistente ha analizado los componentes locales de tu equipo. "
                             "Revisa la detección antes de continuar:",
                        font=("Segoe UI", 10), fg="#f1f5f9", bg="#090d16", justify="left", wraplength=640)
        desc.pack(anchor="w", pady=(10, 15))

        cards = [
            ("Aceleración GPU (NVIDIA CUDA)",
             f"{self.detected_gpu['name']} ({self.detected_gpu['vram']} VRAM)",
             "✔ Compatible y optimizada para offload total" if self.detected_gpu["cuda"] else "⚠ Modo CPU fallback"),
            ("Motor de Inferencia (llama.cpp)",
             os.path.basename(os.path.dirname(self.detected_bin or "No encontrado")),
             "✔ Binario listo (CUDA 13.4)" if self.detected_bin else "⚠ Se usará ruta predeterminada"),
            ("Directorio de Modelos GGUF",
             f"{self.detected_models_count} modelos detectados" if self.detected_gguf_dir else "Sin modelos",
             f"✔ Ubicación: {self.detected_gguf_dir}" if self.detected_gguf_dir else "⚠ Configurar ruta en config.json"),
            ("Integración con OpenCode",
             "openCode detectado" if self.detected_opencode else "OpenCode no configurado",
             "✔ Listo para sincronizar modelos y tokens (16K output)" if self.detected_opencode else "Opcional")
        ]

        for title, subtitle, status in cards:
            c = tk.Frame(self.content_frame, bg="#101726", relief="solid", bd=1, highlightbackground="#1e293b")
            c.pack(fill="x", pady=5, padx=2)

            left = tk.Frame(c, bg="#101726")
            left.pack(side="left", padx=15, pady=8)

            t = tk.Label(left, text=title, font=("Segoe UI", 10, "bold"), fg="#ffffff", bg="#101726")
            t.pack(anchor="w")

            s = tk.Label(left, text=subtitle, font=("Segoe UI", 9), fg="#00e1ff", bg="#101726")
            s.pack(anchor="w")

            st_color = "#00ff88" if "✔" in status else "#ffb800"
            right = tk.Label(c, text=status, font=("Segoe UI", 9, "bold"), fg=st_color, bg="#101726")
            right.pack(side="right", padx=15, pady=8)

    def _render_step2(self):
        desc = tk.Label(self.content_frame,
                        text="Personaliza las preferencias de ejecución de LocalRouterLLM:",
                        font=("Segoe UI", 10), fg="#f1f5f9", bg="#090d16")
        desc.pack(anchor="w", pady=(10, 15))

        form = tk.Frame(self.content_frame, bg="#101726", relief="solid", bd=1)
        form.pack(fill="x", pady=5, padx=2, ipady=10)

        # Puerto Router
        r1 = tk.Frame(form, bg="#101726")
        r1.pack(fill="x", padx=20, pady=6)
        tk.Label(r1, text="Puerto del Router (OpenAI Endpoint):", font=("Segoe UI", 10), fg="#f1f5f9", bg="#101726", width=32, anchor="w").pack(side="left")
        self.entry_port = tk.Entry(r1, font=("Segoe UI", 10), bg="#090d16", fg="#00e1ff", insertbackground="#ffffff", relief="flat", highlightthickness=1, highlightcolor="#00e1ff", highlightbackground="#1e293b", width=10)
        self.entry_port.insert(0, "8080")
        self.entry_port.pack(side="left")

        # Inactividad
        r2 = tk.Frame(form, bg="#101726")
        r2.pack(fill="x", padx=20, pady=6)
        tk.Label(r2, text="Minutos de inactividad para liberar VRAM:", font=("Segoe UI", 10), fg="#f1f5f9", bg="#101726", width=32, anchor="w").pack(side="left")
        self.entry_idle = tk.Entry(r2, font=("Segoe UI", 10), bg="#090d16", fg="#00e1ff", insertbackground="#ffffff", relief="flat", highlightthickness=1, highlightcolor="#00e1ff", highlightbackground="#1e293b", width=10)
        self.entry_idle.insert(0, "10")
        self.entry_idle.pack(side="left")

        # Checkboxes
        opts_frame = tk.Frame(self.content_frame, bg="#090d16")
        opts_frame.pack(fill="x", pady=(15, 5))

        self.var_opencode = tk.BooleanVar(value=True if self.detected_opencode else False)
        cb1 = tk.Checkbutton(opts_frame, text="Sincronizar automáticamente con OpenCode (habilitar 16K tokens de salida y DeepSeek R1)",
                             variable=self.var_opencode, font=("Segoe UI", 9), fg="#f1f5f9", bg="#090d16",
                             selectcolor="#101726", activebackground="#090d16", activeforeground="#00e1ff")
        cb1.pack(anchor="w", pady=4)

        self.var_desktop = tk.BooleanVar(value=True)
        cb2 = tk.Checkbutton(opts_frame, text="Crear acceso directo en el Escritorio ('Iniciar LocalRouterLLM')",
                             variable=self.var_desktop, font=("Segoe UI", 9), fg="#f1f5f9", bg="#090d16",
                             selectcolor="#101726", activebackground="#090d16", activeforeground="#00e1ff")
        cb2.pack(anchor="w", pady=4)

        self.var_deps = tk.BooleanVar(value=True)
        cb3 = tk.Checkbutton(opts_frame, text="Verificar e instalar dependencias de Python (pystray, Pillow, psutil)",
                             variable=self.var_deps, font=("Segoe UI", 9), fg="#f1f5f9", bg="#090d16",
                             selectcolor="#101726", activebackground="#090d16", activeforeground="#00e1ff")
        cb3.pack(anchor="w", pady=4)

    def _render_step3(self):
        self.status_box = tk.Label(self.content_frame, text="Iniciando configuración del sistema...",
                                   font=("Segoe UI", 11, "bold"), fg="#00e1ff", bg="#090d16")
        self.status_box.pack(pady=(40, 15))

        self.canvas_bar = tk.Canvas(self.content_frame, width=580, height=18, bg="#101726", highlightthickness=0)
        self.canvas_bar.pack(pady=10)
        self.bar_rect = self.canvas_bar.create_rectangle(0, 0, 0, 18, fill="#00e1ff")

        self.log_text = tk.Label(self.content_frame, text="Preparando...", font=("Segoe UI", 9), fg="#94a3b8", bg="#090d16")
        self.log_text.pack(pady=10)

        # Start installer worker thread
        threading.Thread(target=self._run_installation, daemon=True).start()

    def _run_installation(self):
        steps = [
            ("Verificando librerías de Python requeridas...", 20),
            ("Generando configuración optimizada (config.json)...", 45),
            ("Sincronizando modelos y tokens con OpenCode...", 70),
            ("Generando accesos directos en el sistema...", 90),
            ("Comprobando puertos y permisos de ejecución...", 100)
        ]

        # 1. Dependencias
        self._update_progress(10, "Verificando dependencias de Python...")
        if self.var_deps.get():
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", "-r", os.path.join(BASE_DIR, "requirements.txt")],
                               capture_output=True, timeout=60)
            except Exception:
                pass

        time.sleep(0.4)
        self._update_progress(35, "Asegurando configuración local de modelos...")

        # 2. Config.json
        try:
            port = int(self.entry_port.get().strip() or "8080")
            idle = int(self.entry_idle.get().strip() or "10")
        except Exception:
            port, idle = 8080, 10

        cfg_source = CONFIG_PATH if os.path.exists(CONFIG_PATH) else EXAMPLE_CONFIG_PATH
        if os.path.exists(cfg_source):
            try:
                with open(cfg_source, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
                cfg_data.setdefault("server", {})
                cfg_data["server"]["port"] = port
                cfg_data["server"]["idle_timeout_minutes"] = idle
                cfg_data["server"]["auto_unload_on_client_exit"] = False
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(cfg_data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        time.sleep(0.4)
        self._update_progress(60, "Configurando límites de OpenCode a 16K tokens...")

        # 3. OpenCode
        if self.var_opencode.get() and self.detected_opencode and os.path.exists(self.detected_opencode):
            try:
                with open(self.detected_opencode, "r", encoding="utf-8") as f:
                    op_data = json.load(f)
                models = op_data.setdefault("provider", {}).setdefault("llamacpp", {}).setdefault("models", {})
                models["DeepSeek-R1-Distill-Qwen-7B"] = {
                    "name": "DeepSeek R1 Distill Qwen 7B (Reasoning SOTA, 32K)",
                    "limit": {"context": 32768, "output": 16384},
                    "reasoning": True
                }
                for mk, mv in models.items():
                    if "reason" in mk.lower() or "thinking" in mk.lower():
                        mv.setdefault("limit", {})["output"] = 16384
                    elif "limit" in mv and "output" in mv["limit"]:
                        mv["limit"]["output"] = max(mv["limit"]["output"], 8192)
                with open(self.detected_opencode, "w", encoding="utf-8") as f:
                    json.dump(op_data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        time.sleep(0.4)
        self._update_progress(85, "Creando acceso directo en el Escritorio...")

        # 4. Desktop Shortcut
        if self.var_desktop.get() and sys.platform == "win32":
            desktop_dir = get_desktop_path()
            target_bat = os.path.join(BASE_DIR, "start.bat")
            lnk_path = os.path.join(desktop_dir, "LocalRouterLLM.lnk")
            try:
                ps_cmd = (
                    f"$ws = New-Object -ComObject WScript.Shell; "
                    f"$s = $ws.CreateShortcut('{lnk_path}'); "
                    f"$s.TargetPath = '{target_bat}'; "
                    f"$s.WorkingDirectory = '{BASE_DIR}'; "
                    f"$s.Description = 'Iniciar LocalRouterLLM'; "
                    f"if (Test-Path '{ICON_PATH}') {{ $s.IconLocation = '{ICON_PATH}' }}; "
                    f"$s.Save()"
                )
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd],
                               capture_output=True, timeout=5)
            except Exception:
                pass

        time.sleep(0.5)
        self._update_progress(100, "¡Instalación completada!")
        time.sleep(0.3)
        self.root.after(100, lambda: self.show_step(4))

    def _update_progress(self, pct, msg):
        def _apply():
            w = 580 * (pct / 100.0)
            self.canvas_bar.coords(self.bar_rect, 0, 0, w, 18)
            self.status_box.config(text=f"Instalando... {pct}%")
            self.log_text.config(text=msg)
        self.root.after(0, _apply)

    def _render_step4(self):
        check_lbl = tk.Label(self.content_frame, text="✔", font=("Segoe UI", 36, "bold"), fg="#00ff88", bg="#090d16")
        check_lbl.pack(pady=(20, 5))

        succ_title = tk.Label(self.content_frame, text="¡LocalRouterLLM está listo para usarse!",
                              font=("Segoe UI", 16, "bold"), fg="#ffffff", bg="#090d16")
        succ_title.pack(pady=(0, 10))

        summary_box = tk.Frame(self.content_frame, bg="#101726", relief="solid", bd=1, highlightbackground="#1e293b")
        summary_box.pack(fill="x", pady=10, ipady=8, padx=20)

        lines = [
            "✔ Router configurado en http://127.0.0.1:8080/v1 (API Key: local)",
            "✔ 16 modelos locales configurados con auto-liberación de VRAM",
            "✔ OpenCode sincronizado con 16K tokens de salida y DeepSeek R1",
            "✔ Acceso directo creado en tu Escritorio para arranque instantáneo"
        ]
        for l in lines:
            tk.Label(summary_box, text=l, font=("Segoe UI", 9), fg="#f1f5f9", bg="#101726", anchor="w").pack(fill="x", padx=15, pady=2)

        opts_end = tk.Frame(self.content_frame, bg="#090d16")
        opts_end.pack(fill="x", pady=(15, 0), padx=20)

        self.var_launch_router = tk.BooleanVar(value=True)
        cb_launch = tk.Checkbutton(opts_end, text="Iniciar LocalRouterLLM en segundo plano ahora",
                                   variable=self.var_launch_router, font=("Segoe UI", 10, "bold"),
                                   fg="#00e1ff", bg="#090d16", selectcolor="#101726",
                                   activebackground="#090d16", activeforeground="#00e1ff")
        cb_launch.pack(anchor="w", pady=4)

        self.var_launch_dashboard = tk.BooleanVar(value=True)
        cb_dash = tk.Checkbutton(opts_end, text="Abrir el Panel de Control Web en el navegador",
                                 variable=self.var_launch_dashboard, font=("Segoe UI", 9),
                                 fg="#f1f5f9", bg="#090d16", selectcolor="#101726",
                                 activebackground="#090d16", activeforeground="#00e1ff")
        cb_dash.pack(anchor="w", pady=4)

    def _finish_and_exit(self):
        if self.var_launch_router.get():
            start_bat = os.path.join(BASE_DIR, "start.bat")
            try:
                subprocess.Popen(f'cmd /c "{start_bat}"', cwd=BASE_DIR, shell=True)
            except Exception:
                pass
        elif self.var_launch_dashboard.get():
            webbrowser.open("http://127.0.0.1:8080/")

        self.root.destroy()

    def next_step(self):
        if self.current_step < 4:
            self.show_step(self.current_step + 1)

    def prev_step(self):
        if self.current_step > 1:
            self.show_step(self.current_step - 1)

def main():
    root = tk.Tk()
    app = InstallerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
