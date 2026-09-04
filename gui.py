#!/usr/bin/env python3
"""
Tkinter GUI for comic_downloader.py.

Ships with Python's standard library (no extra install beyond the project's
requirements.txt). Run with: python gui.py
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from comic_downloader import DEFAULT_UA, run_job, slugify


class DownloaderGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Comic Page Downloader")
        self.geometry("640x520")
        self.minsize(560, 420)

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None

        self._build_widgets()
        self.after(100, self._drain_log_queue)

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}

        form = ttk.Frame(self)
        form.pack(fill="x", **pad)
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Page URL").grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.url_var).grid(row=0, column=1, columnspan=2, sticky="ew")

        ttk.Label(form, text="Output folder").grid(row=1, column=0, sticky="w")
        self.out_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.out_var).grid(row=1, column=1, sticky="ew")
        ttk.Button(form, text="Browse...", command=self._browse_out).grid(row=1, column=2, padx=(4, 0))

        ttk.Label(form, text="CSS selector (optional)").grid(row=2, column=0, sticky="w")
        self.selector_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.selector_var).grid(row=2, column=1, columnspan=2, sticky="ew")

        ttk.Label(form, text="Delay between images (s)").grid(row=3, column=0, sticky="w")
        self.delay_var = tk.StringVar(value="0.5")
        ttk.Entry(form, textvariable=self.delay_var, width=8).grid(row=3, column=1, sticky="w")

        self.pdf_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="Also compile to PDF", variable=self.pdf_var).grid(
            row=4, column=1, sticky="w"
        )

        self.start_btn = ttk.Button(self, text="Download", command=self._start)
        self.start_btn.pack(pady=(4, 8))

        self.log_box = scrolledtext.ScrolledText(self, state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        note = (
            "Only use this on pages you have the right to save from: your own\n"
            "uploads, public-domain archives, or chapters officially released for free."
        )
        ttk.Label(self, text=note, foreground="#666666", justify="left").pack(
            fill="x", padx=8, pady=(0, 8)
        )

    def _browse_out(self) -> None:
        chosen = filedialog.askdirectory()
        if chosen:
            self.out_var.set(chosen)

    def _log(self, message: str) -> None:
        self._log_queue.put(message)

    def _drain_log_queue(self) -> None:
        while True:
            try:
                message = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_box.configure(state="normal")
            self.log_box.insert("end", message + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(100, self._drain_log_queue)

    def _start(self) -> None:
        if self._worker and self._worker.is_alive():
            return

        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("Missing URL", "Enter a page URL first.")
            return

        try:
            delay = float(self.delay_var.get())
        except ValueError:
            messagebox.showerror("Invalid delay", "Delay must be a number.")
            return

        out_text = self.out_var.get().strip()
        out_dir = Path(out_text) if out_text else Path(slugify(url))
        selector = self.selector_var.get().strip() or None
        make_pdf = self.pdf_var.get()

        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        self.start_btn.configure(state="disabled", text="Downloading...")
        self._worker = threading.Thread(
            target=self._run_job_thread,
            args=(url, out_dir, selector, make_pdf, delay),
            daemon=True,
        )
        self._worker.start()

    def _run_job_thread(
        self, url: str, out_dir: Path, selector: str | None, make_pdf: bool, delay: float
    ) -> None:
        try:
            run_job(
                url,
                out_dir,
                selector=selector,
                make_pdf=make_pdf,
                delay=delay,
                user_agent=DEFAULT_UA,
                log=self._log,
            )
        except Exception as exc:  # noqa: BLE001 - surface any failure to the log/user
            self._log(f"ERROR: {exc}")
        finally:
            self.after(0, self._finish)

    def _finish(self) -> None:
        self.start_btn.configure(state="normal", text="Download")


if __name__ == "__main__":
    DownloaderGUI().mainloop()
