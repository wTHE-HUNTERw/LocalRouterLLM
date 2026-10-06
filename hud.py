"""
Standalone Loading HUD Process for LocalRouterLLM
Runs in its own process with its own Tkinter main thread to avoid any Tcl threading issues.
Listens on sys.stdin for real-time status updates:
  STATUS:<message>
  READY
  FAILED
"""

import sys
import os
import time
import threading

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

class StandaloneHUD:
    def __init__(self, model_name="Modelo IA", est_seconds=4.0):
        self.model_name = model_name
        self.est_seconds = max(2.0, float(est_seconds))
        self.progress = 0.0
        self.is_done = False
        self.is_failed = False
        self.is_running = True
        self.start_time = time.time()
        self.status_text = "Iniciando carga de pesos en VRAM..."

        self.root = tk.Tk()
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

        # Stdin listener thread
        self.stdin_thread = threading.Thread(target=self._listen_stdin, daemon=True)
        self.stdin_thread.start()

        self.root.after(30, self._update_loop)
        self.root.mainloop()

    def _draw_ui(self, w, h):
        # Marco exterior y glow
        self.canvas.create_rectangle(1, 1, w - 1, h - 1, outline="#00e1ff", width=2)
        self.canvas.create_rectangle(2, 2, w - 2, h - 2, outline="#0a2a40", width=1)

        # Barra superior decorativa
        self.canvas.create_rectangle(2, 2, w - 2, 4, fill="#00e1ff", outline="")

        # Badge icono de IA
        self.canvas.create_rectangle(16, 14, 38, 36, fill="#0c2333", outline="#00e1ff", width=1)
        self.canvas.create_text(27, 25, text="⚡", font=("Segoe UI", 11), fill="#00e1ff")

        # Titulo y Modelo
        self.canvas.create_text(46, 17, text="CARGANDO EN GPU / VRAM", font=("Segoe UI", 8, "bold"), fill="#00e1ff", anchor="w")
        short_name = self.model_name if len(self.model_name) <= 32 else self.model_name[:29] + "..."
        self.canvas.create_text(46, 31, text=short_name, font=("Segoe UI", 10, "bold"), fill="#ffffff", anchor="w")

        # Barra de progreso de fondo
        self.bar_x1, self.bar_y1 = 16, 50
        self.bar_x2, self.bar_y2 = w - 16, 62
        self.canvas.create_rectangle(self.bar_x1, self.bar_y1, self.bar_x2, self.bar_y2, fill="#131b26", outline="#1e2d40", width=1)

        # Barra de progreso dinámica
        self.bar_fill_id = self.canvas.create_rectangle(self.bar_x1, self.bar_y1, self.bar_x1, self.bar_y2, fill="#00e1ff", outline="")

        # Estado y porcentaje
        self.status_id = self.canvas.create_text(16, 75, text=self.status_text, font=("Segoe UI", 8), fill="#8b9bb4", anchor="w")
        self.pct_id = self.canvas.create_text(w - 16, 75, text="0% • 0.0s", font=("Segoe UI", 8, "bold"), fill="#00e1ff", anchor="e")

    def _listen_stdin(self):
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("STATUS:"):
                    self.status_text = line[7:]
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

        elapsed = time.time() - self.start_time

        # Timeout de seguridad si el router muere (60s)
        if elapsed > 90 and not self.is_done:
            self._destroy()
            return

        if not self.is_done and not self.is_failed:
            ratio = min(elapsed / self.est_seconds, 1.0)
            target = 8.0 + ratio * 84.0
            self.progress += (target - self.progress) * 0.15
            self.progress = min(self.progress, 93.0)

            pct_int = int(self.progress)
            self.canvas.itemconfig(self.pct_id, text=f"{pct_int}% • {elapsed:.1f}s")
            self.canvas.itemconfig(self.status_id, text=self.status_text)
        elif self.is_failed:
            self.canvas.itemconfig(self.pct_id, text="FALLO", fill="#ff4444")
            self.canvas.itemconfig(self.status_id, text="❌ Error al cargar modelo en VRAM", fill="#ff4444")
            self.canvas.itemconfig(self.bar_fill_id, fill="#ff4444")
            self.root.after(2000, self._destroy)
            return
        else:  # is_done
            self.progress += (100.0 - self.progress) * 0.45
            if self.progress >= 99.5:
                self.progress = 100.0

            pct_int = int(self.progress)
            self.canvas.itemconfig(self.pct_id, text=f"{pct_int}% • {elapsed:.1f}s", fill="#00ff88")
            self.canvas.itemconfig(self.status_id, text="✔ Modelo listo y activo en VRAM", fill="#00ff88")
            self.canvas.itemconfig(self.bar_fill_id, fill="#00ff88")

        total_w = self.bar_x2 - self.bar_x1
        fill_w = self.bar_x1 + (total_w * (self.progress / 100.0))
        self.canvas.coords(self.bar_fill_id, self.bar_x1, self.bar_y1, fill_w, self.bar_y2)

        if self.is_done and self.progress >= 99.9:
            self.root.after(800, self._destroy)
            return

        if self.is_running:
            self.root.after(30, self._update_loop)

    def _destroy(self):
        self.is_running = False
        try:
            self.root.destroy()
        except Exception:
            pass

if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else "Modelo IA"
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
    StandaloneHUD(model_name=model, est_seconds=duration)
