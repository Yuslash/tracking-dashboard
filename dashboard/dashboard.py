import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.widgets import DateEntry
from ttkbootstrap.tooltip import ToolTip
import pymongo
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime, timedelta, timezone
import threading
import time

# --- Database Connection ---
try:
    client = pymongo.MongoClient("mongodb://localhost:27017/")
    db = client["activity_tracker"]
    collection = db["daily_summary"]
    print("Dashboard connected to MongoDB.")
except pymongo.errors.ConnectionFailure as e:
    print(f"Could not connect to MongoDB: {e}")
    client = None

# --- Main Application Controller ---
class DashboardApp(ttk.Window):
    def __init__(self):
        super().__init__(themename="darkly")
        self.title("Productivity Dashboard")
        self.geometry("1600x900")

        if not client:
            ttk.Label(self, text="Failed to connect to MongoDB.", font=("Segoe UI", 12), bootstyle=DANGER).pack(pady=50)
            return

        self.current_user = None
        self.running = True

        self._configure_styles()
        self._create_layout()
        self._create_frames()
        self._start_background_tasks()
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _configure_styles(self):
        style = ttk.Style()
        style.configure("Card.TFrame", bordercolor="#444444", borderwidth=1, relief="flat", background="#2b2b2b")
        style.configure("Card.TLabelframe", bordercolor="#444444", background="#2b2b2b")
        style.configure("Card.TLabelframe.Label", font=("Segoe UI", 12, "bold"), foreground="#ffffff")
        style.configure("Nav.TButton", font=("Segoe UI", 11), padding=(10, 8), anchor="w")
        style.map("Nav.TButton", background=[('active', '#007bff'), ('selected', '#007bff')])
        style.configure("User.Treeview", font=("Segoe UI", 11), rowheight=30, background="#2b2b2b", foreground="#ffffff")
        style.map("User.Treeview", background=[('selected', '#007bff')])
        style.configure("User.Treeview.Heading", font=("Segoe UI", 11, "bold"), background="#343a40", foreground="#ffffff")

    def _create_layout(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=BOTH, expand=True)
        self.nav_frame = ttk.Frame(main_frame, width=220, bootstyle="secondary")
        self.nav_frame.pack(side=LEFT, fill=Y)
        self.nav_frame.pack_propagate(False)
        self.container = ttk.Frame(main_frame, padding=10)
        self.container.pack(side=LEFT, fill=BOTH, expand=True)
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)
        
        ttk.Label(self.nav_frame, text="Navigation", font=("Segoe UI", 14, "bold"), bootstyle="inverse-secondary", padding=10).pack(fill=X)
        self.nav_buttons = {}
        for name, text in [("UserStatusFrame", "👤 User Status"), ("DashboardViewFrame", "📊 Dashboard")]:
            btn = ttk.Button(self.nav_frame, text=text, style="Nav.TButton", command=lambda f=name: self.show_frame(f))
            btn.pack(fill=X, padx=10, pady=5)
            self.nav_buttons[name] = btn

    def _create_frames(self):
        self.frames = {}
        for F in (UserStatusFrame, DashboardViewFrame):
            frame = F(self.container, self)
            self.frames[F.__name__] = frame
            frame.grid(row=0, column=0, sticky=NSEW)
        self.show_frame("UserStatusFrame")

    def _start_background_tasks(self):
        self.user_status_updater = threading.Thread(target=self.continuously_update_user_statuses, daemon=True)
        self.user_status_updater.start()

    def show_frame(self, frame_name):
        if frame_name == "DashboardViewFrame" and not self.current_user:
            # --- FIX 2: Correct order of arguments for ToolTip ---
            ToolTip(self.nav_buttons["DashboardViewFrame"], "Select a user from the 'User Status' page first.", bootstyle="danger-inverse", delay=100)
            return
        
        frame = self.frames[frame_name]
        frame.tkraise()
        for name, btn in self.nav_buttons.items():
            btn.config(bootstyle="primary" if name == frame_name else "secondary-outline")

    def user_selected(self, user_id):
        self.current_user = user_id
        self.frames["DashboardViewFrame"].prepare_dashboard()
        self.show_frame("DashboardViewFrame")

    def continuously_update_user_statuses(self):
        while self.running:
            try:
                if "UserStatusFrame" in self.frames and self.frames["UserStatusFrame"].winfo_exists() and self.frames["UserStatusFrame"].winfo_viewable():
                    self.frames["UserStatusFrame"].update_user_list()
            except Exception as e:
                print(f"Error in background update: {e}")
            time.sleep(30)

    def on_closing(self):
        self.running = False
        self.destroy()

# --- Helper Functions ---
def format_seconds(seconds):
    return str(timedelta(seconds=int(seconds)))

def create_kpi_card(parent, title, string_var, column):
    card = ttk.Frame(parent, style="Card.TFrame", padding=15)
    card.grid(row=0, column=column, sticky=EW, padx=10, pady=5)
    ttk.Label(card, text=title, font=("Segoe UI", 11), bootstyle="light").pack()
    ttk.Label(card, textvariable=string_var, font=("Segoe UI", 24, "bold"), bootstyle="primary").pack()

# --- User Status View ---
class UserStatusFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self._create_widgets()

    def _create_widgets(self):
        header = ttk.Frame(self)
        header.pack(fill=X, pady=(0, 10))
        ttk.Label(header, text="User Activity Status", font=("Segoe UI", 16, "bold")).pack(side=LEFT)
        refresh_btn = ttk.Button(header, text="🔄 Refresh", command=self.update_user_list, bootstyle="info-outline")
        refresh_btn.pack(side=RIGHT)
        ToolTip(refresh_btn, "Fetch latest statuses now")

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=BOTH, expand=True)
        self.user_tree = ttk.Treeview(tree_frame, columns=('User', 'Status', 'Time', 'Reason'), show='headings', style="User.Treeview")
        
        self.user_tree.heading('User', text='User', anchor=W)
        self.user_tree.column('User', anchor=W, width=150, stretch=True)
        self.user_tree.heading('Status', text='Status', anchor=CENTER)
        self.user_tree.column('Status', anchor=CENTER, width=100, stretch=False)
        self.user_tree.heading('Time', text="Today's Total", anchor=E)
        self.user_tree.column('Time', anchor=E, width=120, stretch=False)
        self.user_tree.heading('Reason', text='Details', anchor=W)
        self.user_tree.column('Reason', anchor=W, width=200, stretch=True)
        
        self.user_tree.tag_configure("Online", foreground="#28a745"); self.user_tree.tag_configure("Offline", foreground="#dc3545"); self.user_tree.tag_configure("Idle", foreground="#ffc107")
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=VERTICAL, command=self.user_tree.yview, bootstyle="round-dark")
        self.user_tree.configure(yscrollcommand=scrollbar.set)
        self.user_tree.pack(side=LEFT, fill=BOTH, expand=True); scrollbar.pack(side=RIGHT, fill=Y)
        self.user_tree.bind("<<TreeviewSelect>>", self.on_user_select)

    def update_user_list(self):
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            pipeline = [{"$match": {"date": today_str}}, {"$project": {"user_id": 1, "status": 1, "last_seen": 1, "applications": 1, "offline_reason": 1}}]
            users_data = list(collection.aggregate(pipeline))
            user_statuses = []
            for doc in users_data:
                status, reason = doc.get('status', 'Offline'), doc.get('offline_reason', '')
                last_seen = doc.get('last_seen')

                # --- FIX 1: Make datetime objects compatible before comparison ---
                if last_seen and last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                
                if status == "Online" and last_seen and (datetime.now(timezone.utc) - last_seen) > timedelta(minutes=2):
                    status, reason = "Offline", "Connection timeout"

                user_statuses.append({"id": doc['user_id'], "status": status, "reason": reason, "time": format_seconds(sum(doc.get('applications', {}).values()))})
            
            self.after(0, self.populate_tree, user_statuses)
        except Exception as e:
            print(f"Error querying user statuses: {e}")

    def populate_tree(self, user_statuses):
        self.user_tree.delete(*self.user_tree.get_children())
        for user in sorted(user_statuses, key=lambda u: u['id']):
            self.user_tree.insert('', END, iid=user['id'], values=(user['id'], user['status'], user['time'], user['reason']), tags=(user['status'].split(' ')[0],))

    def on_user_select(self, event):
        selection = self.user_tree.selection()
        if selection:
            self.controller.user_selected(selection[0])

# --- Dashboard Analytics View ---
class DashboardViewFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self._create_permanent_widgets()

    def _create_permanent_widgets(self):
        self.placeholder_label = ttk.Label(self, text="Please select a user from the 'User Status' page to view their dashboard.", font=("Segoe UI", 14), bootstyle="info")
        self.placeholder_label.pack(pady=50)
        self.main_content = ttk.Frame(self)

        self.filters_frame = ttk.Labelframe(self.main_content, text="Dashboard", padding=15, style="Card.TLabelframe")
        self.filters_frame.pack(fill=X, pady=(0, 15))
        ttk.Label(self.filters_frame, text="Start Date:").pack(side=LEFT, padx=(0, 5))
        self.start_date_entry = DateEntry(self.filters_frame, bootstyle=INFO, dateformat="%Y-%m-%d")
        self.start_date_entry.entry.insert(0, (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'))
        self.start_date_entry.pack(side=LEFT, padx=(0, 15))
        ttk.Label(self.filters_frame, text="End Date:").pack(side=LEFT, padx=(0, 5))
        self.end_date_entry = DateEntry(self.filters_frame, bootstyle=INFO, dateformat="%Y-%m-%d")
        self.end_date_entry.pack(side=LEFT, padx=(0, 15))
        self.load_button = ttk.Button(self.filters_frame, text="Load Data", command=self.load_data, bootstyle="success-outline")
        self.load_button.pack(side=LEFT)
        
        kpi_frame = ttk.Labelframe(self.main_content, text="Key Metrics for Date Range", padding=15, style="Card.TLabelframe")
        kpi_frame.pack(fill=X, pady=15)
        kpi_frame.grid_columnconfigure((0, 1, 2), weight=1)
        self.total_time_var, self.idle_time_var, self.top_app_var = ttk.StringVar(), ttk.StringVar(), ttk.StringVar()
        create_kpi_card(kpi_frame, "Total Active Time", self.total_time_var, 0)
        create_kpi_card(kpi_frame, "Total Idle Time", self.idle_time_var, 1)
        create_kpi_card(kpi_frame, "Top Application", self.top_app_var, 2)
        
        graphs_frame = ttk.Frame(self.main_content)
        graphs_frame.pack(fill=BOTH, expand=True, pady=15)
        graphs_frame.grid_columnconfigure((0, 1), weight=1); graphs_frame.grid_rowconfigure(0, weight=1)
        
        self.fig_bar, self.ax_bar = plt.subplots(figsize=(6, 5), dpi=100, facecolor="#2b2b2b")
        bar_chart_labelframe = ttk.Labelframe(graphs_frame, text="Application Usage", style="Card.TLabelframe")
        bar_chart_labelframe.grid(row=0, column=0, sticky=NSEW, padx=(0, 10))
        FigureCanvasTkAgg(self.fig_bar, master=bar_chart_labelframe).get_tk_widget().pack(fill=BOTH, expand=True, padx=10, pady=5)
        
        self.fig_line, self.ax_line = plt.subplots(figsize=(6, 5), dpi=100, facecolor="#2b2b2b")
        line_chart_labelframe = ttk.Labelframe(graphs_frame, text="Daily Trends", style="Card.TLabelframe")
        line_chart_labelframe.grid(row=0, column=1, sticky=NSEW, padx=(10, 0))
        FigureCanvasTkAgg(self.fig_line, master=line_chart_labelframe).get_tk_widget().pack(fill=BOTH, expand=True, padx=10, pady=5)
        
    def prepare_dashboard(self):
        self.placeholder_label.pack_forget()
        self.main_content.pack(fill=BOTH, expand=True)
        self.filters_frame.config(text=f"Dashboard for: {self.controller.current_user}")
        self.load_data()

    def load_data(self):
        query = {"user_id": self.controller.current_user, "date": {"$gte": self.start_date_entry.entry.get(), "$lte": self.end_date_entry.entry.get()}}
        df = pd.DataFrame(list(collection.find(query)))
        if df.empty:
            self.clear_visuals()
            return
        self.update_kpis(df)
        self.draw_app_chart(df)
        self.draw_trends_chart(df)

    def clear_visuals(self):
        self.total_time_var.set("00:00:00"); self.idle_time_var.set("00:00:00"); self.top_app_var.set("No Data")
        for ax in [self.ax_bar, self.ax_line]:
            ax.clear(); ax.set_facecolor("#333333"); ax.text(0.5, 0.5, 'No Data for Range', ha='center', color="#fff", va='center')
        self.fig_bar.canvas.draw_idle(); self.fig_line.canvas.draw_idle()

    def update_kpis(self, df):
        app_seconds, all_apps = 0, {}
        for app_dict in df['applications'].dropna():
            if isinstance(app_dict, dict):
                app_seconds += sum(app_dict.values())
                for app, time_val in app_dict.items(): all_apps[app] = all_apps.get(app, 0) + time_val
        self.total_time_var.set(format_seconds(app_seconds))
        self.idle_time_var.set(format_seconds(df['total_idle_seconds'].sum()))
        self.top_app_var.set(max(all_apps, key=all_apps.get).replace('_', '.') if all_apps else "N/A")

    def draw_app_chart(self, df):
        self.ax_bar.clear(); self.ax_bar.set_facecolor("#333333")
        all_apps = {}
        for app_dict in df['applications'].dropna():
            if isinstance(app_dict, dict):
                for app, time_val in app_dict.items(): all_apps[app.replace('_', '.')] = all_apps.get(app.replace('_', '.'), 0) + time_val
        if not all_apps:
            self.ax_bar.text(0.5, 0.5, 'No App Data', ha='center', va='center', color="#fff"); self.fig_bar.canvas.draw_idle(); return
        app_series = pd.Series(all_apps).sort_values().tail(10)
        sns.barplot(x=app_series.values / 3600, y=app_series.index, ax=self.ax_bar, palette="viridis_r", orient='h')
        self.ax_bar.set_xlabel("Total Hours", color="#fff"); self.ax_bar.set_ylabel(""); self.ax_bar.tick_params(colors="#fff")
        self.fig_bar.tight_layout(); self.fig_bar.canvas.draw_idle()

    def draw_trends_chart(self, df):
        self.ax_line.clear(); self.ax_line.set_facecolor("#333333")
        df['date'] = pd.to_datetime(df['date']); df = df.sort_values('date').set_index('date')
        df['productive_hours'] = df['applications'].apply(lambda x: sum(x.values())/3600 if isinstance(x, dict) else 0)
        df['idle_hours'] = df['total_idle_seconds'].fillna(0) / 3600
        df['productive_hours'].plot(ax=self.ax_line, marker='o', label='Productive', color='#28a745')
        df['idle_hours'].plot(ax=self.ax_line, marker='x', linestyle='--', label='Idle', color='#ffc107')
        self.ax_line.set_ylabel("Hours", color="#fff"); self.ax_line.set_xlabel(""); self.ax_line.legend(facecolor="#333", labelcolor="#fff")
        self.ax_line.tick_params(colors="#fff", axis='x', rotation=25); self.ax_line.grid(True, linestyle='--', alpha=0.3)
        self.fig_line.tight_layout(); self.fig_line.canvas.draw_idle()

if __name__ == "__main__":
    app = DashboardApp()
    app.mainloop()