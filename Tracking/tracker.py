import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.tooltip import ToolTip
import threading
import time
import pymongo
import psutil
import win32process
import win32gui
from ctypes import Structure, windll, c_uint, sizeof, byref
import getpass
from datetime import datetime

# --- CONFIGURATION ---
IDLE_THRESHOLD_SECONDS = 60  # Time in seconds to consider the user idle
SWITCH_CONFIRM_SECONDS = 3   # Require app to be in focus for this long to count as a switch
GUI_UPDATE_MS = 5000         # Update the GUI stats every 5000 milliseconds (5 seconds)

# --- MongoDB Connection ---
try:
    client = pymongo.MongoClient("mongodb://localhost:27017/")
    db = client["activity_tracker"]
    collection = db["daily_summary"]
    print("Connected to MongoDB")
except pymongo.errors.ConnectionFailure as e:
    print(f"Could not connect to MongoDB: {e}")
    client = None

# --- Helper Function ---
def format_seconds(seconds):
    """Converts seconds into HH:MM:SS string format."""
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

# --- Idle Time Detection ---
class LASTINPUTINFO(Structure):
    _fields_ = [('cbSize', c_uint), ('dwTime', c_uint)]

def get_idle_time():
    last_input_info = LASTINPUTINFO()
    last_input_info.cbSize = sizeof(last_input_info)
    windll.user32.GetLastInputInfo(byref(last_input_info))
    millis = windll.kernel32.GetTickCount() - last_input_info.dwTime
    return millis / 1000.0

# --- Activity Tracking Thread ---
class ActivityTracker(threading.Thread):
    def __init__(self, app):
        threading.Thread.__init__(self)
        self.app = app
        self.running = True
        self.user_id = getpass.getuser()
        self.current_app = ""
        self.start_time = time.time()
        self.idle = False
        self.potential_next_app = ""
        self.switch_pending_time = None

    def run(self):
        self.current_app = self.get_active_app()
        self.start_time = time.time()
        while self.running:
            idle_seconds = get_idle_time()
            active_app_name = self.get_active_app()
            if idle_seconds > IDLE_THRESHOLD_SECONDS:
                if not self.idle:
                    self.update_database(self.current_app, time.time() - self.start_time)
                    self.idle = True
                    self.start_time = time.time()
                    self.clear_pending_switch()
                self.app.update_status(f"Status: Idle ({int(idle_seconds)}s)")
            else:
                if self.idle:
                    self.update_database("idle", time.time() - self.start_time)
                    self.idle = False
                    self.current_app = active_app_name
                    self.start_time = time.time()
                if active_app_name != self.current_app:
                    self.handle_potential_switch(active_app_name)
                else:
                    self.clear_pending_switch()
                self.app.update_status(f"Active App: {self.current_app}")
            time.sleep(1)

    def handle_potential_switch(self, active_app_name):
        if self.potential_next_app != active_app_name:
            self.potential_next_app = active_app_name
            self.switch_pending_time = time.time()
        else:
            if time.time() - self.switch_pending_time > SWITCH_CONFIRM_SECONDS:
                duration = self.switch_pending_time - self.start_time
                self.update_database(self.current_app, duration)
                self.current_app = self.potential_next_app
                self.start_time = self.switch_pending_time
                self.clear_pending_switch()

    def clear_pending_switch(self):
        self.potential_next_app = ""
        self.switch_pending_time = None

    def get_active_app(self):
        try:
            hwnd = win32gui.GetForegroundWindow()
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid <= 0: return "LockScreen"
            process = psutil.Process(pid)
            return process.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return "Unknown"
        except Exception:
            return "Unknown"

    def update_database(self, activity_name, duration_seconds):
        if duration_seconds < 1 or not activity_name or activity_name == "Unknown":
            return
        if not client:
            print("Skipping DB update: No connection.")
            return
        today_str = datetime.now().strftime("%Y-%m-%d")
        doc_id = f"{self.user_id}_{today_str}"
        if activity_name == "idle":
            update_field = "total_idle_seconds"
            print(f"Logged Idle: {duration_seconds:.2f}s")
        else:
            safe_app_name = activity_name.replace('.', '_')
            update_field = f"applications.{safe_app_name}"
            print(f"Logged App: {activity_name}, Duration: {duration_seconds:.2f}s")
        collection.update_one({"_id": doc_id}, {"$inc": {update_field: duration_seconds}, "$setOnInsert": {"user_id": self.user_id, "date": today_str}}, upsert=True)

    def stop(self):
        self.running = False
        duration = time.time() - self.start_time
        if self.idle:
            self.update_database("idle", duration)
        else:
            self.update_database(self.current_app, duration)

# --- GUI Application ---
class App(ttk.Window):
    def __init__(self):
        # Initialize with darkly theme
        super().__init__(themename="darkly")
        
        self.title("Activity Tracker")
        self.geometry("650x550")
        self.resizable(True, True)
        
        # Configure custom styles
        style = ttk.Style()
        style.configure("Custom.Treeview", font=("Segoe UI", 10), rowheight=32, background="#2b2b2b", foreground="#ffffff")
        style.configure("Custom.Treeview.Heading", font=("Segoe UI", 11, "bold"), background="#1e1e1e", foreground="#ffffff")
        style.map("Custom.Treeview", background=[('selected', '#3a3a3a')])
        style.configure("Card.TFrame", bordercolor="#444444", borderwidth=1, relief="flat", background="#2b2b2b")
        
        # --- Main container ---
        container = ttk.Frame(self, padding=(20, 20, 20, 10))
        container.pack(fill=BOTH, expand=True)
        
        # --- Header frame ---
        header_frame = ttk.Frame(container, bootstyle="dark")
        header_frame.pack(fill=X, pady=(0, 15))
        
        # Application title
        ttk.Label(
            header_frame,
            text="Activity Tracker",
            font=("Segoe UI", 18, "bold"),
            bootstyle="inverse-dark"
        ).pack(side=LEFT)
        
        # Status label
        self.status_label = ttk.Label(
            header_frame,
            text="Initializing...",
            font=("Segoe UI", 10),
            bootstyle="light"
        )
        self.status_label.pack(side=RIGHT)
        ToolTip(self.status_label, text="Current application or idle status", bootstyle="inverse-dark")
        
        # --- Card for usage summary ---
        card = ttk.Frame(container, style="Card.TFrame", padding=15)
        card.pack(fill=BOTH, expand=True)
        
        # Summary header with total time
        summary_frame = ttk.Frame(card)
        summary_frame.pack(fill=X, pady=(0, 10))
        
        ttk.Label(
            summary_frame,
            text="Today's Usage Summary",
            font=("Segoe UI", 12, "bold"),
            bootstyle="light"
        ).pack(side=LEFT)
        
        self.total_time_label = ttk.Label(
            summary_frame,
            text="Total: 00:00:00",
            font=("Segoe UI", 10),
            bootstyle="warning"
        )
        self.total_time_label.pack(side=RIGHT)
        
        # --- Treeview for displaying app usage ---
        tree_frame = ttk.Frame(card)
        tree_frame.pack(fill=BOTH, expand=True)
        
        self.tree = ttk.Treeview(
            tree_frame,
            columns=('App', 'Time'),
            show='headings',
            style="Custom.Treeview",
            selectmode="browse"
        )
        self.tree.heading('App', text='Application')
        self.tree.heading('Time', text='Total Usage')
        self.tree.column('App', width=400, stretch=True)
        self.tree.column('Time', width=120, anchor=E, stretch=False)
        self.tree.tag_configure("oddrow", background="#2b2b2b")
        self.tree.tag_configure("evenrow", background="#333333")
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(
            tree_frame,
            orient=VERTICAL,
            command=self.tree.yview,
            bootstyle="round-dark"
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)
        
        # Add tooltip for treeview rows
        self.tree.bind("<Motion>", self._on_treeview_motion)
        
        # --- Button frame ---
        button_frame = ttk.Frame(container, padding=(0, 10, 0, 10))
        button_frame.pack(fill=X)
        
        # Refresh button
        refresh_button = ttk.Button(
            button_frame,
            text="Refresh",
            command=self.update_usage_display,
            bootstyle="info-outline",
            width=12
        )
        refresh_button.pack(side=RIGHT, padx=(0, 10))
        ToolTip(refresh_button, text="Manually refresh the usage data", bootstyle="inverse-dark")
        
        # Exit button
        exit_button = ttk.Button(
            button_frame,
            text="Exit",
            command=self.on_closing,
            bootstyle="danger-outline",
            width=12
        )
        exit_button.pack(side=RIGHT)
        ToolTip(exit_button, text="Close the application", bootstyle="inverse-dark")
        
        # --- Start tracker and GUI updates ---
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.tracker = ActivityTracker(self)
        self.tracker.start()
        self.update_usage_display()

    def _on_treeview_motion(self, event):
        """Display tooltip for Treeview rows on hover."""
        item = self.tree.identify_row(event.y)
        if item:
            values = self.tree.item(item, "values")
            if values:
                ToolTip(self.tree, text=f"{values[0]}: {values[1]}", bootstyle="inverse-dark", delay=200)

    def update_status(self, status_text):
        self.status_label.config(text=status_text)
        # Subtle animation for status update
        self.status_label.configure(bootstyle="warning")
        self.after(200, lambda: self.status_label.configure(bootstyle="light"))

    def update_usage_display(self):
        if not client:
            self.after(GUI_UPDATE_MS, self.update_usage_display)
            return

        today_str = datetime.now().strftime("%Y-%m-%d")
        doc_id = f"{getpass.getuser()}_{today_str}"
        data = collection.find_one({"_id": doc_id})

        for item in self.tree.get_children():
            self.tree.delete(item)

        total_seconds = 0
        if data and "applications" in data:
            app_usage = sorted(data["applications"].items(), key=lambda item: item[1], reverse=True)
            for index, (app_name_safe, seconds) in enumerate(app_usage):
                app_name = app_name_safe.replace('_', '.')
                time_str = format_seconds(seconds)
                tag = "evenrow" if index % 2 == 0 else "oddrow"
                self.tree.insert('', END, values=(app_name, time_str), tags=(tag,))
                total_seconds += seconds

        # Update total time
        self.total_time_label.config(text=f"Total: {format_seconds(total_seconds)}")
        
        self.after(GUI_UPDATE_MS, self.update_usage_display)

    def on_closing(self):
        print("Closing application and saving final activity...")
        self.after_cancel(self.after_id)
        self.tracker.stop()
        self.tracker.join(timeout=2)
        self.destroy()
    
    def after(self, ms, func=None, *args):
        self.after_id = super().after(ms, func, *args)
        return self.after_id

if __name__ == "__main__":
    app = App()
    app.mainloop()