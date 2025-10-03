import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pyttsx3
import os
import json
import re
import time

class ReaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Read Aloud — Enhanced Text-to-Speech")
        self.speaking = False
        self.speak_thread = None
        self.current_engine = None
        self.stop_requested = False
        self.current_file = None
        # Store settings in the script directory, not AppData
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.settings_file = os.path.join(script_dir, "tts_settings.json")
        self.dark_mode = False
        self.clipboard_monitor_enabled = False
        self.last_clipboard = ""
        self.highlight_tag = "highlight"
        self.current_word_indices = []
        
        # Speech Queue System
        self.speech_queue = []
        self.queue_playing = False
        self.current_queue_index = -1
        
        # Load settings
        self.load_settings()
        
        # Initialize engine just to get default settings and voices
        temp_engine = pyttsx3.init()
        self.default_rate = temp_engine.getProperty("rate")
        self.default_volume = temp_engine.getProperty("volume")
        self.voices = temp_engine.getProperty("voices")
        temp_engine.stop()  # Clean up temp engine

        # --- UI ---
        self.txt = tk.Text(root, wrap="word", height=16, undo=True, font=('Arial', 11))
        self.txt.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        
        # Configure highlight tag
        self.txt.tag_config(self.highlight_tag, background="yellow", foreground="black")
        
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
        self.voice_combo = ttk.Combobox(controls, values=list(self.voice_map.keys()), width=18, state="readonly")
        # Pick a default female/neutral if available
        default_name = next((n for n in self.voice_map if "female" in n.lower() or "zira" in n.lower()), list(self.voice_map.keys())[0])
        self.voice_combo.set(default_name)
        self.selected_voice = self.voice_map[default_name]  # Store selected voice
        self.voice_combo.bind("<<ComboboxSelected>>", self.on_voice_change)
        self.voice_combo.grid(row=0, column=10, padx=(0,4))
        
        # Refresh voices button
        refresh_voices_btn = ttk.Button(controls, text="🔄", command=self.refresh_voices, width=3)
        refresh_voices_btn.grid(row=0, column=11, padx=(0,0))

        controls.columnconfigure(6, weight=1)
        controls.columnconfigure(8, weight=1)

        # File operations and additional features
        file_frame = ttk.Frame(root)
        file_frame.pack(fill="x", padx=10, pady=(0,5))
        
        open_btn = ttk.Button(file_frame, text="📁 Open", command=self.on_open)
        save_btn = ttk.Button(file_frame, text="💾 Save", command=self.on_save)
        save_as_btn = ttk.Button(file_frame, text="💾 Save As", command=self.on_save_as)
        export_audio_btn = ttk.Button(file_frame, text="🔊 Export Audio", command=self.on_export_audio)
        search_btn = ttk.Button(file_frame, text="🔍 Find/Replace", command=self.on_search)
        theme_btn = ttk.Button(file_frame, text="🌓 Theme", command=self.toggle_theme)
        settings_btn = ttk.Button(file_frame, text="⚙️ Settings", command=self.on_settings)
        
        open_btn.pack(side="left", padx=(0,6))
        save_btn.pack(side="left", padx=(0,6))
        save_as_btn.pack(side="left", padx=(0,6))
        export_audio_btn.pack(side="left", padx=(0,6))
        search_btn.pack(side="left", padx=(0,6))
        theme_btn.pack(side="left", padx=(0,6))
        settings_btn.pack(side="left", padx=(0,6))
        
        # Clipboard monitor controls
        clipboard_frame = ttk.Frame(file_frame)
        clipboard_frame.pack(side="right", padx=(6,0))
        
        self.clipboard_var = tk.BooleanVar(value=self.clipboard_monitor_enabled)
        clipboard_check = ttk.Checkbutton(clipboard_frame, text="📎 Monitor Clipboard:", 
                                         variable=self.clipboard_var, command=self.toggle_clipboard_monitor)
        clipboard_check.pack(side="left")
        
        # Clipboard action mode (speak or queue)
        self.clipboard_action = tk.StringVar(value="speak")
        clipboard_speak_radio = ttk.Radiobutton(clipboard_frame, text="Speak", 
                                               variable=self.clipboard_action, value="speak")
        clipboard_queue_radio = ttk.Radiobutton(clipboard_frame, text="Queue", 
                                               variable=self.clipboard_action, value="queue")
        clipboard_speak_radio.pack(side="left", padx=(5,0))
        clipboard_queue_radio.pack(side="left")
        
        # Speech Queue Panel
        queue_frame = ttk.LabelFrame(root, text="📋 Speech Queue", padding=5)
        queue_frame.pack(fill="both", expand=False, padx=10, pady=(0,5))
        
        # Queue listbox with scrollbar
        queue_list_frame = ttk.Frame(queue_frame)
        queue_list_frame.pack(side="left", fill="both", expand=True)
        
        queue_scrollbar = ttk.Scrollbar(queue_list_frame, orient="vertical")
        self.queue_listbox = tk.Listbox(queue_list_frame, height=4, 
                                        yscrollcommand=queue_scrollbar.set,
                                        selectmode=tk.SINGLE)
        queue_scrollbar.config(command=self.queue_listbox.yview)
        queue_scrollbar.pack(side="right", fill="y")
        self.queue_listbox.pack(side="left", fill="both", expand=True)
        
        # Queue control buttons
        queue_controls = ttk.Frame(queue_frame)
        queue_controls.pack(side="right", fill="y", padx=(5,0))
        
        ttk.Button(queue_controls, text="➕ Add Current Text", 
                  command=self.add_current_to_queue, width=18).pack(pady=2)
        ttk.Button(queue_controls, text="➕ Add File(s)", 
                  command=self.add_files_to_queue, width=18).pack(pady=2)
        ttk.Button(queue_controls, text="▶ Play Queue", 
                  command=self.play_queue, width=18).pack(pady=2)
        ttk.Button(queue_controls, text="❌ Remove Selected", 
                  command=self.remove_from_queue, width=18).pack(pady=2)
        ttk.Button(queue_controls, text="🗑️ Clear Queue", 
                  command=self.clear_queue, width=18).pack(pady=2)
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(root, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.pack(side="bottom", fill="x")

        # Apply theme
        self.apply_theme()
        
        # Bind keyboard shortcuts
        self.bind_shortcuts()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # Start clipboard monitoring if enabled
        if self.clipboard_monitor_enabled:
            self.monitor_clipboard()

    def load_settings(self):
        """Load settings from JSON file"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    self.dark_mode = settings.get('dark_mode', False)
                    self.clipboard_monitor_enabled = settings.get('clipboard_monitor', False)
                    self.hotkeys = settings.get('hotkeys', self.get_default_hotkeys())
            else:
                self.hotkeys = self.get_default_hotkeys()
        except Exception as e:
            print(f"Failed to load settings: {e}")
            self.hotkeys = self.get_default_hotkeys()
    
    def save_settings(self):
        """Save settings to JSON file"""
        try:
            settings = {
                'dark_mode': self.dark_mode,
                'clipboard_monitor': self.clipboard_monitor_enabled,
                'hotkeys': self.hotkeys
            }
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"Failed to save settings: {e}")
    
    def get_default_hotkeys(self):
        """Return default hotkey mappings"""
        return {
            'speak_all': '<Control-Return>',
            'speak_selected': '<Control-Shift-Return>',
            'stop': '<Escape>',
            'open': '<Control-o>',
            'save': '<Control-s>',
            'save_as': '<Control-Shift-S>',
            'paste': '<Control-v>',
            'clear': '<Control-l>',
            'find': '<Control-f>',
            'export': '<Control-e>'
        }
    
    def bind_shortcuts(self):
        """Bind keyboard shortcuts"""
        # Unbind all existing shortcuts first
        for action, key in self.hotkeys.items():
            try:
                self.root.unbind(key)
            except:
                pass
        
        # Bind shortcuts
        self.root.bind(self.hotkeys['speak_all'], lambda e: self.on_speak())
        self.root.bind(self.hotkeys['speak_selected'], lambda e: self.on_speak_selected())
        self.root.bind(self.hotkeys['stop'], lambda e: self.on_stop())
        self.root.bind(self.hotkeys['open'], lambda e: self.on_open())
        self.root.bind(self.hotkeys['save'], lambda e: self.on_save())
        self.root.bind(self.hotkeys['save_as'], lambda e: self.on_save_as())
        self.root.bind(self.hotkeys['paste'], lambda e: self.on_paste())
        self.root.bind(self.hotkeys['clear'], lambda e: self.on_clear())
        self.root.bind(self.hotkeys['find'], lambda e: self.on_search())
        self.root.bind(self.hotkeys['export'], lambda e: self.on_export_audio())
    
    def apply_theme(self):
        """Apply dark or light theme"""
        if self.dark_mode:
            # Dark theme
            bg_color = "#2b2b2b"
            fg_color = "#ffffff"
            text_bg = "#1e1e1e"
            text_fg = "#d4d4d4"
            self.txt.tag_config(self.highlight_tag, background="#4a4a00", foreground="#ffff00")
            queue_bg = "#1e1e1e"
            queue_fg = "#d4d4d4"
        else:
            # Light theme
            bg_color = "#f0f0f0"
            fg_color = "#000000"
            text_bg = "#ffffff"
            text_fg = "#000000"
            self.txt.tag_config(self.highlight_tag, background="yellow", foreground="black")
            queue_bg = "#ffffff"
            queue_fg = "#000000"
        
        self.root.configure(bg=bg_color)
        self.txt.configure(bg=text_bg, fg=text_fg, insertbackground=text_fg)
        self.queue_listbox.configure(bg=queue_bg, fg=queue_fg)
    
    def toggle_theme(self):
        """Toggle between dark and light theme"""
        self.dark_mode = not self.dark_mode
        self.apply_theme()
        self.save_settings()
        self.status_var.set(f"{'Dark' if self.dark_mode else 'Light'} theme activated")
    
    def toggle_clipboard_monitor(self):
        """Toggle clipboard monitoring"""
        self.clipboard_monitor_enabled = self.clipboard_var.get()
        self.save_settings()
        if self.clipboard_monitor_enabled:
            self.monitor_clipboard()
            self.status_var.set("Clipboard monitoring enabled")
        else:
            self.status_var.set("Clipboard monitoring disabled")
    
    def monitor_clipboard(self):
        """Monitor clipboard for changes and auto-speak or queue"""
        if not self.clipboard_monitor_enabled:
            return
        
        try:
            current_clipboard = self.root.clipboard_get()
            if current_clipboard != self.last_clipboard and current_clipboard.strip():
                self.last_clipboard = current_clipboard
                
                # Check if clipboard content is long enough
                if len(current_clipboard.strip()) > 5:
                    action = self.clipboard_action.get()
                    
                    if action == "speak":
                        # Auto-speak mode (only if not currently speaking)
                        if not self.speaking:
                            self.status_var.set("Auto-speaking clipboard content...")
                            threading.Thread(target=self._speak_worker, args=(current_clipboard,), daemon=True).start()
                    
                    elif action == "queue":
                        # Queue mode - add to speech queue
                        preview = current_clipboard[:50] + "..." if len(current_clipboard) > 50 else current_clipboard
                        self.speech_queue.append({'text': current_clipboard, 'name': f"📋 Clipboard: {preview}"})
                        self.update_queue_display()
                        self.status_var.set(f"Clipboard added to queue ({len(self.speech_queue)} items)")
        except:
            pass
        
        # Check again in 1 second
        if self.clipboard_monitor_enabled:
            self.root.after(1000, self.monitor_clipboard)
    
    def add_current_to_queue(self):
        """Add current text to speech queue"""
        text = self.txt.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Queue", "No text to add to queue.")
            return
        
        # Add to queue with a preview (first 50 chars)
        preview = text[:50] + "..." if len(text) > 50 else text
        self.speech_queue.append({'text': text, 'name': f"Text: {preview}"})
        self.update_queue_display()
        self.status_var.set(f"Added to queue ({len(self.speech_queue)} items)")
    
    def add_files_to_queue(self):
        """Add multiple files to speech queue"""
        file_paths = filedialog.askopenfilenames(
            title="Add Files to Queue",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        
        if file_paths:
            for file_path in file_paths:
                try:
                    with open(file_path, 'r', encoding='utf-8') as file:
                        content = file.read().strip()
                        if content:
                            filename = os.path.basename(file_path)
                            self.speech_queue.append({'text': content, 'name': f"📄 {filename}"})
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to load {file_path}: {str(e)}")
            
            self.update_queue_display()
            self.status_var.set(f"Added {len(file_paths)} file(s) to queue ({len(self.speech_queue)} items)")
    
    def remove_from_queue(self):
        """Remove selected item from queue"""
        selection = self.queue_listbox.curselection()
        if not selection:
            messagebox.showinfo("Queue", "Please select an item to remove.")
            return
        
        index = selection[0]
        del self.speech_queue[index]
        self.update_queue_display()
        self.status_var.set(f"Removed from queue ({len(self.speech_queue)} items)")
    
    def clear_queue(self):
        """Clear all items from queue"""
        if not self.speech_queue:
            return
        
        if messagebox.askyesno("Clear Queue", f"Remove all {len(self.speech_queue)} items from queue?"):
            self.speech_queue.clear()
            self.update_queue_display()
            self.status_var.set("Queue cleared")
    
    def update_queue_display(self):
        """Update the queue listbox display"""
        self.queue_listbox.delete(0, tk.END)
        for i, item in enumerate(self.speech_queue):
            prefix = "▶ " if i == self.current_queue_index and self.queue_playing else "   "
            self.queue_listbox.insert(tk.END, f"{prefix}{i+1}. {item['name']}")
        
        # Highlight current item if playing
        if self.queue_playing and 0 <= self.current_queue_index < len(self.speech_queue):
            self.queue_listbox.itemconfig(self.current_queue_index, bg='lightblue')
    
    def play_queue(self):
        """Start playing items in the queue"""
        if not self.speech_queue:
            messagebox.showinfo("Queue", "Queue is empty. Add items to queue first.")
            return
        
        if self.speaking or self.queue_playing:
            messagebox.showinfo("Queue", "Already speaking. Stop current speech first.")
            return
        
        self.queue_playing = True
        self.stop_requested = False  # Reset stop flag
        self.current_queue_index = 0
        self.status_var.set(f"Playing queue item 1 of {len(self.speech_queue)}")
        self.update_queue_display()
        
        # Start playing the queue
        threading.Thread(target=self._play_queue_worker, daemon=True).start()
    
    def _play_queue_worker(self):
        """Worker thread to play queue items sequentially"""
        com_initialized = False
        
        # Initialize COM for this thread
        try:
            import pythoncom
            pythoncom.CoInitialize()
            com_initialized = True
        except (ImportError, Exception):
            try:
                import win32com.client
                import pythoncom
                pythoncom.CoInitializeEx(0)
                com_initialized = True
            except:
                pass
        
        try:
            while self.queue_playing and self.current_queue_index < len(self.speech_queue):
                if self.stop_requested:
                    break
                
                item = self.speech_queue[self.current_queue_index]
                self.speaking = True
                
                # Update UI to show current item
                self.root.after(0, lambda: self.update_queue_display())
                self.root.after(0, lambda idx=self.current_queue_index: 
                               self.status_var.set(f"Playing queue item {idx+1} of {len(self.speech_queue)}"))
                
                # Disable buttons
                self.root.after(0, lambda: self.speak_btn.state(["disabled"]))
                self.root.after(0, lambda: self.speak_selected_btn.state(["disabled"]))
                
                # Speak the item
                engine = None
                try:
                    engine = pyttsx3.init()
                    self.current_engine = engine
                    
                    engine.setProperty("rate", self.rate.get())
                    engine.setProperty("volume", self.vol.get())
                    if self.selected_voice:
                        engine.setProperty("voice", self.selected_voice)
                    
                    if not self.stop_requested:
                        engine.say(item['text'])
                        engine.runAndWait()
                    
                except Exception as e:
                    err_msg = str(e)
                    self.root.after(0, lambda msg=err_msg: messagebox.showerror("TTS Error", f"Failed to speak queue item: {msg}"))
                    break
                finally:
                    # Cleanup engine
                    if engine:
                        try:
                            del engine
                        except:
                            pass
                    
                    self.current_engine = None
                
                self.speaking = False
                self.current_queue_index += 1
                
                # Small pause between items
                if self.current_queue_index < len(self.speech_queue) and not self.stop_requested:
                    threading.Event().wait(0.5)
            
            # Queue finished
            self.queue_playing = False
            self.current_queue_index = -1
            
            if self.stop_requested:
                self.root.after(0, lambda: self.status_var.set("Queue playback stopped"))
            else:
                self.root.after(0, lambda: self.status_var.set("Queue playback completed"))
            
            self.root.after(0, lambda: self.speak_btn.state(["!disabled"]))
            self.root.after(0, lambda: self.speak_selected_btn.state(["!disabled"]))
            self.root.after(0, lambda: self.update_queue_display())
            self.root.after(0, lambda: self.txt.tag_remove(self.highlight_tag, "1.0", "end"))
            
        except Exception as e:
            self.queue_playing = False
            self.current_queue_index = -1
            self.root.after(0, lambda: messagebox.showerror("Queue Error", f"Queue playback failed: {str(e)}"))
            self.root.after(0, lambda: self.speak_btn.state(["!disabled"]))
            self.root.after(0, lambda: self.speak_selected_btn.state(["!disabled"]))
        finally:
            # Uninitialize COM if it was initialized
            if com_initialized:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except:
                    pass

    def _on_rate_change(self, value):
        self.rate.set(int(float(value)))
    
    def _on_volume_change(self, value):
        self.vol.set(float(value))
    
    def on_voice_change(self, _):
        vid = self.voice_map.get(self.voice_combo.get())
        if vid:
            self.selected_voice = vid
    
    def refresh_voices(self):
        """Refresh the voice list to detect newly installed voices"""
        try:
            # Get current selection
            current_voice_name = self.voice_combo.get()
            
            # Re-initialize engine to get updated voice list
            temp_engine = pyttsx3.init()
            self.voices = temp_engine.getProperty("voices")
            temp_engine.stop()
            
            # Rebuild voice map
            self.voice_map = { (v.name or f"Voice {i}"): v.id for i, v in enumerate(self.voices) }
            
            # Update combobox
            self.voice_combo['values'] = list(self.voice_map.keys())
            
            # Try to restore previous selection, otherwise pick first voice
            if current_voice_name in self.voice_map:
                self.voice_combo.set(current_voice_name)
                self.selected_voice = self.voice_map[current_voice_name]
            else:
                # Pick first voice if previous selection no longer exists
                if self.voice_map:
                    first_voice = list(self.voice_map.keys())[0]
                    self.voice_combo.set(first_voice)
                    self.selected_voice = self.voice_map[first_voice]
            
            # Update status
            self.status_var.set(f"Voices refreshed! Found {len(self.voices)} voice(s)")
            
            # Show info if new voices were found
            messagebox.showinfo("Voices Refreshed", 
                              f"Found {len(self.voices)} voice(s) installed on your system.\n\n"
                              f"To add more voices:\n"
                              f"1. Open Windows Settings\n"
                              f"2. Go to Time & Language → Speech\n"
                              f"3. Click 'Add voices'\n"
                              f"4. Click 🔄 to refresh again!")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh voices: {str(e)}")
            self.status_var.set("Failed to refresh voices")

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
    
    def on_export_audio(self):
        """Export text to audio file"""
        text = self.txt.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Export Audio", "No text to export.")
            return
        
        file_path = filedialog.asksaveasfilename(
            title="Export Audio File",
            defaultextension=".wav",
            filetypes=[("WAV files", "*.wav"), ("MP3 files", "*.mp3")]
        )
        
        if file_path:
            try:
                self.status_var.set("Exporting audio...")
                engine = pyttsx3.init()
                engine.setProperty("rate", self.rate.get())
                engine.setProperty("volume", self.vol.get())
                if self.selected_voice:
                    engine.setProperty("voice", self.selected_voice)
                
                engine.save_to_file(text, file_path)
                engine.runAndWait()
                
                self.status_var.set(f"Audio exported: {os.path.basename(file_path)}")
                messagebox.showinfo("Export Audio", f"Audio successfully exported to:\n{file_path}")
            except Exception as e:
                messagebox.showerror("Export Error", f"Failed to export audio: {str(e)}")
                self.status_var.set("Export failed")
    
    def on_search(self):
        """Open search and replace dialog"""
        SearchDialog(self.root, self.txt)
    
    def on_settings(self):
        """Open settings dialog for hotkey customization"""
        SettingsDialog(self.root, self)
    
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
        """Worker thread for speaking text - with Python 3.13 fix"""
        engine = None
        com_initialized = False
        
        try:
            # Try to initialize COM for this thread (Windows-specific fix for Python 3.13)
            try:
                import pythoncom
                pythoncom.CoInitialize()
                com_initialized = True
            except (ImportError, Exception):
                # pywin32 not installed or COM init failed
                # Try alternative: use CoInitializeEx with COINIT_MULTITHREADED
                try:
                    import win32com.client
                    import pythoncom
                    pythoncom.CoInitializeEx(0)  # COINIT_MULTITHREADED
                    com_initialized = True
                except:
                    pass  # Will try without COM initialization
            
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
            
            # Set up word highlighting callback
            def on_word(name, location, length):
                if self.stop_requested:
                    return
                # Calculate word position in text
                try:
                    self.root.after(0, lambda loc=location, ln=length: self.highlight_word(loc, ln))
                except:
                    pass
            
            # Connect callback if available (not all engines support this)
            try:
                engine.connect('started-word', on_word)
            except:
                pass  # Callback not supported, continue without highlighting
            
            # Simple say and wait
            engine.say(text)
            engine.runAndWait()
            
            # Clear highlighting
            self.root.after(0, lambda: self.txt.tag_remove(self.highlight_tag, "1.0", "end"))
            
        except Exception as e:
            # Use after() to safely show error message from worker thread
            error_msg = str(e)
            self.root.after(0, lambda msg=error_msg: messagebox.showerror("TTS Error", f"Failed to speak text: {msg}"))
        finally:
            # Cleanup engine
            if engine:
                try:
                    del engine
                except:
                    pass
            
            # Uninitialize COM if it was initialized
            if com_initialized:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except:
                    pass
            
            self.current_engine = None
            self.speaking = False
            self.root.after(0, lambda: self.speak_btn.state(["!disabled"]))
            self.root.after(0, lambda: self.speak_selected_btn.state(["!disabled"]))
            self.root.after(0, lambda: self.status_var.set("Ready"))
    
    def highlight_word(self, location, length):
        """Highlight the current word being spoken"""
        try:
            # Remove previous highlight
            self.txt.tag_remove(self.highlight_tag, "1.0", "end")
            
            # Find position in text widget
            start_idx = f"1.0 + {location} chars"
            end_idx = f"1.0 + {location + length} chars"
            
            # Add highlight
            self.txt.tag_add(self.highlight_tag, start_idx, end_idx)
            
            # Auto-scroll to show highlighted word
            self.txt.see(start_idx)
        except Exception:
            pass  # Ignore errors in highlighting

    def on_stop(self):
        # Stop regular speech
        if self.speaking and self.current_engine:
            self.stop_requested = True
            try:
                self.current_engine.stop()
            except Exception:
                pass  # Ignore errors when stopping engine
            self.speaking = False
            self.speak_btn.state(["!disabled"])
            self.speak_selected_btn.state(["!disabled"])
            self.txt.tag_remove(self.highlight_tag, "1.0", "end")  # Clear highlighting
            self.status_var.set("Speech stopped")
        
        # Stop queue playback
        if self.queue_playing:
            self.stop_requested = True
            self.queue_playing = False
            if self.current_engine:
                try:
                    self.current_engine.stop()
                except Exception:
                    pass
            self.current_queue_index = -1
            self.update_queue_display()
            self.status_var.set("Queue playback stopped")

    def on_close(self):
        self.save_settings()
        self.root.destroy()


class SearchDialog:
    """Search and Replace dialog"""
    def __init__(self, parent, text_widget):
        self.text_widget = text_widget
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Find and Replace")
        self.dialog.geometry("450x200")
        self.dialog.resizable(False, False)
        
        # Search frame
        search_frame = ttk.Frame(self.dialog, padding=10)
        search_frame.pack(fill="x")
        
        ttk.Label(search_frame, text="Find:").grid(row=0, column=0, sticky="w", pady=5)
        self.find_entry = ttk.Entry(search_frame, width=40)
        self.find_entry.grid(row=0, column=1, padx=5, pady=5)
        self.find_entry.focus()
        
        ttk.Label(search_frame, text="Replace:").grid(row=1, column=0, sticky="w", pady=5)
        self.replace_entry = ttk.Entry(search_frame, width=40)
        self.replace_entry.grid(row=1, column=1, padx=5, pady=5)
        
        # Options
        options_frame = ttk.Frame(self.dialog, padding=10)
        options_frame.pack(fill="x")
        
        self.case_sensitive = tk.BooleanVar(value=False)
        self.use_regex = tk.BooleanVar(value=False)
        
        ttk.Checkbutton(options_frame, text="Case sensitive", variable=self.case_sensitive).pack(side="left", padx=5)
        ttk.Checkbutton(options_frame, text="Use regex", variable=self.use_regex).pack(side="left", padx=5)
        
        # Buttons
        button_frame = ttk.Frame(self.dialog, padding=10)
        button_frame.pack(fill="x")
        
        ttk.Button(button_frame, text="Find Next", command=self.find_next).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Replace", command=self.replace_one).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Replace All", command=self.replace_all).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Close", command=self.dialog.destroy).pack(side="right", padx=5)
        
        self.search_start = "1.0"
    
    def find_next(self):
        """Find next occurrence"""
        search_term = self.find_entry.get()
        if not search_term:
            return
        
        # Remove previous selection
        self.text_widget.tag_remove("sel", "1.0", "end")
        
        # Search
        flags = []
        if not self.case_sensitive.get():
            flags.append("nocase")
        if self.use_regex.get():
            flags.append("regexp")
        
        pos = self.text_widget.search(search_term, self.search_start, "end", *flags)
        
        if pos:
            end_pos = f"{pos}+{len(search_term)}c"
            self.text_widget.tag_add("sel", pos, end_pos)
            self.text_widget.mark_set("insert", pos)
            self.text_widget.see(pos)
            self.search_start = end_pos
        else:
            messagebox.showinfo("Find", "No more matches found.")
            self.search_start = "1.0"
    
    def replace_one(self):
        """Replace current selection"""
        try:
            selection = self.text_widget.get("sel.first", "sel.last")
            if selection:
                self.text_widget.delete("sel.first", "sel.last")
                self.text_widget.insert("insert", self.replace_entry.get())
                self.find_next()
        except tk.TclError:
            messagebox.showinfo("Replace", "No text selected. Use 'Find Next' first.")
    
    def replace_all(self):
        """Replace all occurrences"""
        search_term = self.find_entry.get()
        replace_term = self.replace_entry.get()
        
        if not search_term:
            return
        
        content = self.text_widget.get("1.0", "end-1c")
        
        if self.use_regex.get():
            flags = 0 if self.case_sensitive.get() else re.IGNORECASE
            new_content, count = re.subn(search_term, replace_term, content, flags=flags)
        else:
            if self.case_sensitive.get():
                count = content.count(search_term)
                new_content = content.replace(search_term, replace_term)
            else:
                # Case insensitive replace
                import re
                pattern = re.compile(re.escape(search_term), re.IGNORECASE)
                new_content = pattern.sub(replace_term, content)
                count = len(pattern.findall(content))
        
        if count > 0:
            self.text_widget.delete("1.0", "end")
            self.text_widget.insert("1.0", new_content)
            messagebox.showinfo("Replace All", f"Replaced {count} occurrence(s).")
        else:
            messagebox.showinfo("Replace All", "No matches found.")


class SettingsDialog:
    """Settings dialog for hotkey customization"""
    def __init__(self, parent, app):
        self.app = app
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Settings - Hotkey Customization")
        self.dialog.geometry("500x400")
        self.dialog.resizable(False, False)
        
        # Instructions
        instruction_frame = ttk.Frame(self.dialog, padding=10)
        instruction_frame.pack(fill="x")
        ttk.Label(instruction_frame, text="Click on a hotkey field and press the desired key combination.", 
                 wraplength=450).pack()
        
        # Hotkeys frame with scrollbar
        canvas_frame = ttk.Frame(self.dialog, padding=10)
        canvas_frame.pack(fill="both", expand=True)
        
        canvas = tk.Canvas(canvas_frame, height=250)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        hotkey_frame = ttk.Frame(canvas)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.create_window((0, 0), window=hotkey_frame, anchor="nw")
        
        self.hotkey_entries = {}
        action_labels = {
            'speak_all': 'Speak All Text',
            'speak_selected': 'Speak Selected Text',
            'stop': 'Stop Speaking',
            'open': 'Open File',
            'save': 'Save File',
            'save_as': 'Save As',
            'paste': 'Paste Text',
            'clear': 'Clear Text',
            'find': 'Find/Replace',
            'export': 'Export Audio'
        }
        
        row = 0
        for action, label in action_labels.items():
            ttk.Label(hotkey_frame, text=label, width=20).grid(row=row, column=0, padx=5, pady=5, sticky="w")
            
            entry = ttk.Entry(hotkey_frame, width=25)
            entry.insert(0, self.app.hotkeys.get(action, ''))
            entry.grid(row=row, column=1, padx=5, pady=5)
            
            # Bind key press to capture hotkey
            entry.bind('<KeyPress>', lambda e, a=action: self.capture_hotkey(e, a))
            
            self.hotkey_entries[action] = entry
            row += 1
        
        hotkey_frame.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))
        
        # Buttons
        button_frame = ttk.Frame(self.dialog, padding=10)
        button_frame.pack(fill="x")
        
        ttk.Button(button_frame, text="Save", command=self.save_hotkeys).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Reset to Defaults", command=self.reset_defaults).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.dialog.destroy).pack(side="right", padx=5)
    
    def capture_hotkey(self, event, action):
        """Capture hotkey combination"""
        modifiers = []
        if event.state & 0x4:  # Control
            modifiers.append("Control")
        if event.state & 0x1:  # Shift
            modifiers.append("Shift")
        if event.state & 0x20000:  # Alt
            modifiers.append("Alt")
        
        key = event.keysym
        if key not in ['Control_L', 'Control_R', 'Shift_L', 'Shift_R', 'Alt_L', 'Alt_R']:
            if modifiers:
                hotkey = f"<{'-'.join(modifiers)}-{key}>"
            else:
                hotkey = f"<{key}>"
            
            self.hotkey_entries[action].delete(0, "end")
            self.hotkey_entries[action].insert(0, hotkey)
        
        return "break"
    
    def save_hotkeys(self):
        """Save new hotkey mappings"""
        new_hotkeys = {}
        for action, entry in self.hotkey_entries.items():
            hotkey = entry.get().strip()
            if hotkey:
                new_hotkeys[action] = hotkey
        
        self.app.hotkeys = new_hotkeys
        self.app.bind_shortcuts()
        self.app.save_settings()
        
        messagebox.showinfo("Settings", "Hotkeys saved successfully!")
        self.dialog.destroy()
    
    def reset_defaults(self):
        """Reset to default hotkeys"""
        defaults = self.app.get_default_hotkeys()
        for action, entry in self.hotkey_entries.items():
            entry.delete(0, "end")
            entry.insert(0, defaults.get(action, ''))


if __name__ == "__main__":
    root = tk.Tk()
    app = ReaderApp(root)
    root.minsize(700, 400)
    root.mainloop()
