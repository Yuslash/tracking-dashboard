import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.tooltip import ToolTip
import threading
import time
import pymongo
import psutil
import win32process
import win32gui
import win32con
import win32api
from ctypes import Structure, windll, c_uint, sizeof, byref
import getpass
from datetime import datetime, timezone

# --- CONFIGURATION ---
IDLE_THRESHOLD_SECONDS = 60
SWITCH_CONFIRM_SECONDS = 3
GUI_UPDATE_MS = 5000
HEARTBEAT_SECONDS = 30

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
        self.last_heartbeat_time = 0

    def run(self):
        self.update_status_in_db("Online")
        self.current_app = self.get_active_app()
        self.start_time = time.time()

        while self.running:
            now = time.time()
            if now - self.last_heartbeat_time > HEARTBEAT_SECONDS:
                current_status = "Idle" if self.idle else "Online"
                self.update_status_in_db(current_status)
                self.last_heartbeat_time = now

            idle_seconds = get_idle_time()
            active_app_name = self.get_active_app()

            if idle_seconds > IDLE_THRESHOLD_SECONDS:
                if not self.idle:
                    self.update_database(self.current_app, time.time() - self.start_time)
                    self.idle = True
                    self.start_time = time.time()
                    self.clear_pending_switch()
                    self.update_status_in_db("Idle")
                self.app.update_status(f"Status: Idle ({int(idle_seconds)}s)")
            else:
                if self.idle:
                    self.update_database("idle", time.time() - self.start_time)
                    self.idle = False
                    self.current_app = active_app_name
                    self.start_time = time.time()
                    self.update_status_in_db("Online")
                if active_app_name != self.current_app:
                    self.handle_potential_switch(active_app_name)
                else:
                    self.clear_pending_switch()
                self.app.update_status(f"Status: Active [{self.current_app}]")
            time.sleep(1)

    def handle_potential_switch(self, active_app_name):
        if self.potential_next_app != active_app_name:
            self.potential_next_app = active_app_name
            self.switch_pending_time = time.time()
        else:
            if self.switch_pending_time and time.time() - self.switch_pending_time > SWITCH_CONFIRM_SECONDS:
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

    def update_status_in_db(self, status, reason=None):
        if not client: return
        today_str = datetime.now().strftime("%Y-%m-%d")
        doc_id = f"{self.user_id}_{today_str}"
        update_doc = {
            "$set": {"status": status, "last_seen": datetime.now(timezone.utc)},
            "$setOnInsert": {"user_id": self.user_id, "date": today_str}
        }
        if reason:
            update_doc["$set"]["offline_reason"] = reason
        collection.update_one({"_id": doc_id}, update_doc, upsert=True)
        print(f"Status updated to: {status}" + (f" (Reason: {reason})" if reason else ""))

    def update_database(self, activity_name, duration_seconds):
        if duration_seconds < 1 or not activity_name or activity_name == "Unknown": return
        if not client: return
        today_str = datetime.now().strftime("%Y-%m-%d")
        doc_id = f"{self.user_id}_{today_str}"
        update_field = f"applications.{activity_name.replace('.', '_')}" if activity_name != "idle" else "total_idle_seconds"
        collection.update_one({"_id": doc_id}, {"$inc": {update_field: duration_seconds}}, upsert=True)

    def stop(self, reason="Exited gracefully"):
        if not self.running: return
        self.running = False
        duration = time.time() - self.start_time
        activity = "idle" if self.idle else self.current_app
        self.update_database(activity, duration)
        self.update_status_in_db("Offline", reason=reason)

# --- GUI Application with System Event Handling ---
class App(ttk.Window):
    def __init__(self):
        super().__init__(themename="darkly")
        self.title("Activity Tracker"); self.geometry("650x550"); self.resizable(True, True)
        self._configure_styles(); self._create_widgets()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.tracker = ActivityTracker(self)
        self.tracker.start()
        
        self._setup_windows_message_handling()
        self.update_usage_display()

    def _configure_styles(self):
        style = ttk.Style()
        style.configure("Custom.Treeview", font=("Segoe UI", 10), rowheight=32, background="#2b2b2b", foreground="#ffffff")
        style.configure("Custom.Treeview.Heading", font=("Segoe UI", 11, "bold"), background="#1e1e1e", foreground="#ffffff")
        style.map("Custom.Treeview", background=[('selected', '#3a3a3a')])
        style.configure("Card.TFrame", bordercolor="#444444", borderwidth=1, relief="flat", background="#2b2b2b")

    def _create_widgets(self):
        container = ttk.Frame(self, padding=(20, 20, 20, 10)); container.pack(fill=BOTH, expand=True)
        header_frame = ttk.Frame(container, bootstyle="dark"); header_frame.pack(fill=X, pady=(0, 15))
        ttk.Label(header_frame, text="Activity Tracker", font=("Segoe UI", 18, "bold"), bootstyle="inverse-dark").pack(side=LEFT)
        self.status_label = ttk.Label(header_frame, text="Initializing...", font=("Segoe UI", 10), bootstyle="light"); self.status_label.pack(side=RIGHT)
        ToolTip(self.status_label, text="Current application or idle status", bootstyle="inverse-dark")
        card = ttk.Frame(container, style="Card.TFrame", padding=15); card.pack(fill=BOTH, expand=True)
        summary_frame = ttk.Frame(card); summary_frame.pack(fill=X, pady=(0, 10))
        ttk.Label(summary_frame, text="Today's Usage Summary", font=("Segoe UI", 12, "bold"), bootstyle="light").pack(side=LEFT)
        self.total_time_label = ttk.Label(summary_frame, text="Total: 00:00:00", font=("Segoe UI", 10), bootstyle="warning"); self.total_time_label.pack(side=RIGHT)
        tree_frame = ttk.Frame(card); tree_frame.pack(fill=BOTH, expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=('App', 'Time'), show='headings', style="Custom.Treeview", selectmode="browse")
        self.tree.heading('App', text='Application'); self.tree.heading('Time', text='Total Usage')
        self.tree.column('App', width=400, stretch=True); self.tree.column('Time', width=120, anchor=E, stretch=False)
        scrollbar = ttk.Scrollbar(tree_frame, orient=VERTICAL, command=self.tree.yview, bootstyle="round-dark"); self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True); scrollbar.pack(side=RIGHT, fill=Y)
        button_frame = ttk.Frame(container, padding=(0, 10, 0, 10)); button_frame.pack(fill=X)
        refresh_button = ttk.Button(button_frame, text="Refresh", command=self.update_usage_display, bootstyle="info-outline", width=12); refresh_button.pack(side=RIGHT, padx=(0, 10))
        exit_button = ttk.Button(button_frame, text="Exit", command=self.on_closing, bootstyle="danger-outline", width=12); exit_button.pack(side=RIGHT)
        
    def _setup_windows_message_handling(self):
        self.hwnd = self.winfo_id()
        self.old_wndproc = win32gui.SetWindowLong(self.hwnd, win32con.GWL_WNDPROC, self.wndproc)

    def wndproc(self, hwnd, msg, wparam, lparam):
        # Listen for system shutdown/logoff events
        if msg == win32con.WM_QUERYENDSESSION:
            print("System is shutting down. Saving final data.")
            self.on_closing(reason="System shutdown/logoff")
            return True # Important to return True to allow shutdown
        
        # Listen for system sleep/resume events
        if msg == win32con.WM_POWERBROADCAST:
            if wparam == win32con.PBT_APMSUSPEND:
                print("System is going to sleep.")
                self.tracker.update_status_in_db("Offline", reason="System sleep")
            elif wparam == win32con.PBT_APMRESUMEAUTOMATIC:
                print("System is resuming.")
                self.tracker.update_status_in_db("Online")
        
        # Pass all other messages to the original handler
        return win32gui.CallWindowProc(self.old_wndproc, hwnd, msg, wparam, lparam)

    def update_status(self, status_text):
        self.status_label.config(text=status_text)

    def update_usage_display(self):
        if not client: self.after(GUI_UPDATE_MS, self.update_usage_display); return
        today_str = datetime.now().strftime("%Y-%m-%d")
        doc_id = f"{getpass.getuser()}_{today_str}"
        data = collection.find_one({"_id": doc_id})
        self.tree.delete(*self.tree.get_children())
        total_seconds = 0
        if data and "applications" in data:
            for app, seconds in sorted(data["applications"].items(), key=lambda item: item[1], reverse=True):
                self.tree.insert('', END, values=(app.replace('_', '.'), format_seconds(seconds)))
                total_seconds += seconds
        self.total_time_label.config(text=f"Total: {format_seconds(total_seconds)}")
        self.after_id = self.after(GUI_UPDATE_MS, self.update_usage_display)

    def on_closing(self, reason="Exited gracefully"):
        print(f"Closing application ({reason})...")
        # Unregister window message handler to prevent errors on close
        if hasattr(self, 'old_wndproc'):
            win32api.SetWindowLong(self.hwnd, win32con.GWL_WNDPROC, self.old_wndproc)
        
        self.tracker.stop(reason)
        self.tracker.join(timeout=2)
        if hasattr(self, 'after_id'): self.after_cancel(self.after_id)
        self.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()