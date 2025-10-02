import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pyttsx3
import os

class ReaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Read Aloud — Text-to-Speech with File Support")
        self.speaking = False
        self.speak_thread = None
        self.current_engine = None
        self.stop_requested = False
        self.current_file = None
        
        # Initialize engine just to get default settings and voices
        temp_engine = pyttsx3.init()
        self.default_rate = temp_engine.getProperty("rate")
        self.default_volume = temp_engine.getProperty("volume")
        self.voices = temp_engine.getProperty("voices")
        temp_engine.stop()  # Clean up temp engine

        # --- UI ---
        self.txt = tk.Text(root, wrap="word", height=16, undo=True, font=('Arial', 11))
        self.txt.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=self.txt.yview)
        scrollbar.pack(side="right", fill="y")
        self.txt.configure(yscrollcommand=scrollbar.set)

        controls = ttk.Frame(root)
        controls.pack(fill="x", padx=10, pady=(0,10))

        self.speak_btn = ttk.Button(controls, text="▶ Speak All", command=self.on_speak)
        self.speak_selected_btn = ttk.Button(controls, text="▶ Speak Selected", command=self.on_speak_selected)
        self.stop_btn  = ttk.Button(controls, text="■ Stop",  command=self.on_stop)
        paste_btn      = ttk.Button(controls, text="📋 Paste", command=self.on_paste)
        clear_btn      = ttk.Button(controls, text="🗑️ Clear", command=self.on_clear)

        self.speak_btn.grid(row=0, column=0, padx=(0,6))
        self.speak_selected_btn.grid(row=0, column=1, padx=(0,6))
        self.stop_btn.grid(row=0, column=2, padx=(0,6))
        paste_btn.grid(row=0, column=3, padx=(0,6))
        clear_btn.grid(row=0, column=4, padx=(0,12))

        # Rate
        ttk.Label(controls, text="Rate").grid(row=0, column=5, padx=(16,4))
        self.rate = tk.IntVar(value=self.default_rate)
        self.rate_scale = ttk.Scale(controls, from_=100, to=250, orient="horizontal",
                                    command=self._on_rate_change)
        self.rate_scale.set(self.rate.get())
        self.rate_scale.grid(row=0, column=6, sticky="ew", padx=(0,8))

        # Volume
        ttk.Label(controls, text="Volume").grid(row=0, column=7, padx=(8,4))
        self.vol = tk.DoubleVar(value=self.default_volume)
        self.vol_scale = ttk.Scale(controls, from_=0.1, to=1.0, orient="horizontal",
                                   command=self._on_volume_change)
        self.vol_scale.set(self.vol.get())
        self.vol_scale.grid(row=0, column=8, sticky="ew", padx=(0,8))

        # Voice selector
        ttk.Label(controls, text="Voice").grid(row=0, column=9, padx=(8,4))
        self.voice_map = { (v.name or f"Voice {i}"): v.id for i, v in enumerate(self.voices) }
        self.voice_combo = ttk.Combobox(controls, values=list(self.voice_map.keys()), width=22, state="readonly")
        # Pick a default female/neutral if available
        default_name = next((n for n in self.voice_map if "female" in n.lower() or "zira" in n.lower()), list(self.voice_map.keys())[0])
        self.voice_combo.set(default_name)
        self.selected_voice = self.voice_map[default_name]  # Store selected voice
        self.voice_combo.bind("<<ComboboxSelected>>", self.on_voice_change)
        self.voice_combo.grid(row=0, column=10, padx=(0,0))

        controls.columnconfigure(6, weight=1)
        controls.columnconfigure(8, weight=1)

        # File operations
        file_frame = ttk.Frame(root)
        file_frame.pack(fill="x", padx=10, pady=(0,5))
        
        open_btn = ttk.Button(file_frame, text="📁 Open", command=self.on_open)
        save_btn = ttk.Button(file_frame, text="💾 Save", command=self.on_save)
        save_as_btn = ttk.Button(file_frame, text="💾 Save As", command=self.on_save_as)
        
        open_btn.pack(side="left", padx=(0,6))
        save_btn.pack(side="left", padx=(0,6))
        save_as_btn.pack(side="left", padx=(0,6))
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(root, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.pack(side="bottom", fill="x")

        # Keyboard shortcuts
        self.root.bind("<Control-Return>", lambda e: self.on_speak())
        self.root.bind("<Control-Shift-Return>", lambda e: self.on_speak_selected())
        self.root.bind("<Escape>", lambda e: self.on_stop())
        self.root.bind("<Control-o>", lambda e: self.on_open())
        self.root.bind("<Control-s>", lambda e: self.on_save())
        self.root.bind("<Control-Shift-S>", lambda e: self.on_save_as())
        self.root.bind("<Control-v>", lambda e: self.on_paste())
        self.root.bind("<Control-l>", lambda e: self.on_clear())
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _on_rate_change(self, value):
        self.rate.set(int(float(value)))
    
    def _on_volume_change(self, value):
        self.vol.set(float(value))
    
    def on_voice_change(self, _):
        vid = self.voice_map.get(self.voice_combo.get())
        if vid:
            self.selected_voice = vid

    def on_paste(self):
        try:
            self.txt.insert("insert", self.root.clipboard_get())
            self.status_var.set("Text pasted")
        except tk.TclError:
            messagebox.showinfo("Clipboard", "Clipboard is empty.")
    
    def on_clear(self):
        self.txt.delete("1.0", "end")
        self.status_var.set("Text cleared")
    
    def on_open(self):
        file_path = filedialog.askopenfilename(
            title="Open Text File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as file:
                    content = file.read()
                self.txt.delete("1.0", "end")
                self.txt.insert("1.0", content)
                self.current_file = file_path
                self.status_var.set(f"Opened: {os.path.basename(file_path)}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to open file: {str(e)}")
    
    def on_save(self):
        if self.current_file:
            try:
                with open(self.current_file, 'w', encoding='utf-8') as file:
                    file.write(self.txt.get("1.0", "end"))
                self.status_var.set(f"Saved: {os.path.basename(self.current_file)}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save file: {str(e)}")
        else:
            self.on_save_as()
    
    def on_save_as(self):
        file_path = filedialog.asksaveasfilename(
            title="Save Text File",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as file:
                    file.write(self.txt.get("1.0", "end"))
                self.current_file = file_path
                self.status_var.set(f"Saved: {os.path.basename(file_path)}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save file: {str(e)}")
    
    def on_speak_selected(self):
        if self.speaking:
            return
        try:
            selected_text = self.txt.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
            if not selected_text:
                messagebox.showinfo("Read Aloud", "Please select some text first.")
                return
            self.speaking = True
            self.stop_requested = False
            self.speak_btn.state(["disabled"])
            self.speak_selected_btn.state(["disabled"])
            self.status_var.set("Speaking selected text...")
            self.speak_thread = threading.Thread(target=self._speak_worker, args=(selected_text,), daemon=True)
            self.speak_thread.start()
        except tk.TclError:
            messagebox.showinfo("Read Aloud", "Please select some text first.")

    def on_speak(self):
        if self.speaking:
            return
        text = self.txt.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Read Aloud", "Paste or type some text first.")
            return
        self.speaking = True
        self.stop_requested = False
        self.speak_btn.state(["disabled"])
        self.speak_selected_btn.state(["disabled"])
        self.status_var.set("Speaking all text...")
        self.speak_thread = threading.Thread(target=self._speak_worker, args=(text,), daemon=True)
        self.speak_thread.start()

    def _speak_worker(self, text):
        try:
            # Create a fresh engine for each speech to avoid lifecycle issues
            engine = pyttsx3.init()
            self.current_engine = engine  # Store reference for stop functionality
            
            # Apply current settings to the new engine
            engine.setProperty("rate", self.rate.get())
            engine.setProperty("volume", self.vol.get())
            if self.selected_voice:
                engine.setProperty("voice", self.selected_voice)
            
            # Check if stop was requested before starting
            if self.stop_requested:
                return
            
            engine.say(text)
            engine.runAndWait()
            
        except Exception as e:
            # Use after() to safely show error message from worker thread
            self.root.after(0, lambda: messagebox.showerror("TTS Error", f"Failed to speak text: {str(e)}"))
        finally:
            self.current_engine = None  # Clear reference
            self.speaking = False
            self.speak_btn.state(["!disabled"])
            self.speak_selected_btn.state(["!disabled"])
            self.root.after(0, lambda: self.status_var.set("Ready"))

    def on_stop(self):
        if self.speaking and self.current_engine:
            self.stop_requested = True
            try:
                self.current_engine.stop()
            except Exception:
                pass  # Ignore errors when stopping engine
            self.speaking = False
            self.speak_btn.state(["!disabled"])
            self.speak_selected_btn.state(["!disabled"])
            self.status_var.set("Speech stopped")

    def on_close(self):
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = ReaderApp(root)
    root.minsize(640, 360)
    root.mainloop()
