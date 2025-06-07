import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.widgets import DateEntry
from ttkbootstrap.tooltip import ToolTip
import pymongo
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime, timedelta

# --- Database Connection ---
try:
    client = pymongo.MongoClient("mongodb://localhost:27017/")
    db = client["activity_tracker"]
    collection = db["daily_summary"]
    print("Dashboard connected to MongoDB.")
except pymongo.errors.ConnectionFailure as e:
    print(f"Could not connect to MongoDB: {e}")
    client = None

# --- Main Dashboard Application ---
class DashboardApp(ttk.Window):
    def __init__(self):
        super().__init__(themename="darkly")
        self.title("Productivity Dashboard")
        self.geometry("1280x800")
        self.resizable(True, True)

        # Configure custom styles
        style = ttk.Style()
        style.configure("Card.TFrame", bordercolor="#444444", borderwidth=1, relief="flat", background="#2b2b2b")
        style.configure("Card.TLabelframe", bordercolor="#444444", background="#2b2b2b")
        style.configure("Card.TLabelframe.Label", font=("Segoe UI", 11, "bold"), foreground="#ffffff")

        if not client:
            ttk.Label(
                self,
                text="Failed to connect to MongoDB. Please check the connection and restart.",
                font=("Segoe UI", 12),
                bootstyle=DANGER
            ).pack(pady=50)
            return

        self.setup_ui()
        self.load_available_users()

    def setup_ui(self):
        """Creates the main layout and widgets for the dashboard."""
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=BOTH, expand=True)

        # --- 1. Filters Frame ---
        filters_frame = ttk.Labelframe(main_frame, text="Filters", padding=15, style="Card.TLabelframe")
        filters_frame.pack(fill=X, pady=(0, 15))

        ttk.Label(filters_frame, text="User:", font=("Segoe UI", 10)).pack(side=LEFT, padx=(0, 10))
        self.user_var = ttk.StringVar()
        self.user_dropdown = ttk.Combobox(
            filters_frame,
            textvariable=self.user_var,
            state="readonly",
            font=("Segoe UI", 10),
            width=20
        )
        self.user_dropdown.pack(side=LEFT, padx=(0, 20))
        ToolTip(self.user_dropdown, text="Select a user to view their data", bootstyle="inverse-dark")

        ttk.Label(filters_frame, text="Start Date:", font=("Segoe UI", 10)).pack(side=LEFT, padx=(0, 10))
        self.start_date_entry = DateEntry(filters_frame, bootstyle=INFO, dateformat="%Y-%m-%d")
        self.start_date_entry.pack(side=LEFT, padx=(0, 20))
        self.start_date_entry.entry.delete(0, END)
        self.start_date_entry.entry.insert(0, (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'))
        ToolTip(self.start_date_entry, text="Select the start date for data range", bootstyle="inverse-dark")

        ttk.Label(filters_frame, text="End Date:", font=("Segoe UI", 10)).pack(side=LEFT, padx=(0, 10))
        self.end_date_entry = DateEntry(filters_frame, bootstyle=INFO, dateformat="%Y-%m-%d")
        self.end_date_entry.pack(side=LEFT, padx=(0, 20))
        self.end_date_entry.entry.insert(0, datetime.now().strftime('%Y-%m-%d'))
        ToolTip(self.end_date_entry, text="Select the end date for data range", bootstyle="inverse-dark")

        self.load_button = ttk.Button(
            filters_frame,
            text="Load Data",
            command=self.load_data_and_refresh_dashboard,
            bootstyle="success-outline",
            width=12
        )
        self.load_button.pack(side=LEFT)
        ToolTip(self.load_button, text="Load data for the selected user and date range", bootstyle="inverse-dark")

        # --- 2. KPIs Frame ---
        kpi_frame = ttk.Labelframe(main_frame, text="Key Metrics", padding=15, style="Card.TLabelframe")
        kpi_frame.pack(fill=X, pady=15)
        kpi_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.total_time_var = ttk.StringVar(value="--:--:--")
        self.idle_time_var = ttk.StringVar(value="--:--:--")
        self.top_app_var = ttk.StringVar(value="N/A")

        self.create_kpi_card(kpi_frame, "Total Time Tracked", self.total_time_var, 0)
        self.create_kpi_card(kpi_frame, "Total Idle Time", self.idle_time_var, 1)
        self.create_kpi_card(kpi_frame, "Top Application", self.top_app_var, 2)

        # --- 3. Graphs Frame ---
        graphs_frame = ttk.Frame(main_frame)
        graphs_frame.pack(fill=BOTH, expand=True, pady=15)
        graphs_frame.grid_columnconfigure((0, 1), weight=1)
        graphs_frame.grid_rowconfigure(0, weight=1)

        # Bar chart for app usage
        self.bar_chart_frame = ttk.Labelframe(graphs_frame, text="Application Usage Breakdown", padding=10, style="Card.TLabelframe")
        self.bar_chart_frame.grid(row=0, column=0, sticky=NSEW, padx=(0, 10))
        self.fig_bar, self.ax_bar = plt.subplots(figsize=(6, 5), dpi=100, facecolor="#2b2b2b")
        self.ax_bar.set_facecolor("#333333")
        self.canvas_bar = FigureCanvasTkAgg(self.fig_bar, master=self.bar_chart_frame)
        self.canvas_bar.get_tk_widget().pack(fill=BOTH, expand=True)

        # Line chart for daily trends
        self.line_chart_frame = ttk.Labelframe(graphs_frame, text="Daily Trends", padding=10, style="Card.TLabelframe")
        self.line_chart_frame.grid(row=0, column=1, sticky=NSEW, padx=(10, 0))
        self.fig_line, self.ax_line = plt.subplots(figsize=(6, 5), dpi=100, facecolor="#2b2b2b")
        self.ax_line.set_facecolor("#333333")
        self.canvas_line = FigureCanvasTkAgg(self.fig_line, master=self.line_chart_frame)
        self.canvas_line.get_tk_widget().pack(fill=BOTH, expand=True)

    def create_kpi_card(self, parent, title, string_var, column):
        """Helper to create a single KPI card."""
        card_frame = ttk.Frame(parent, style="Card.TFrame", padding=10)
        card_frame.grid(row=0, column=column, sticky=EW, padx=5, pady=5)
        title_label = ttk.Label(card_frame, text=title, font=("Segoe UI", 11, "bold"), bootstyle="light")
        title_label.pack(pady=(0, 5))
        value_label = ttk.Label(card_frame, textvariable=string_var, font=("Segoe UI", 22), bootstyle="primary")
        value_label.pack()
        ToolTip(value_label, text=title, bootstyle="inverse-dark")

    def load_available_users(self):
        """Populates the user dropdown with distinct users from the DB."""
        users = collection.distinct("user_id")
        self.user_dropdown['values'] = users
        if users:
            self.user_dropdown.set(users[0])

    def format_seconds(self, seconds):
        """Converts seconds into HH:MM:SS string format."""
        s = int(seconds)
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def query_mongo_to_dataframe(self, user, start_date, end_date):
        """Queries MongoDB and returns a pandas DataFrame."""
        try:
            start_date_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_date_dt = datetime.strptime(end_date, '%Y-%m-%d')
        except ValueError:
            print("Invalid date format. Using default range.")
            start_date_dt = datetime.now() - timedelta(days=7)
            end_date_dt = datetime.now()

        query = {
            "user_id": user,
            "date": {
                "$gte": start_date_dt.strftime('%Y-%m-%d'),
                "$lte": end_date_dt.strftime('%Y-%m-%d')
            }
        }
        data = list(collection.find(query))
        return pd.DataFrame(data)

    def load_data_and_refresh_dashboard(self):
        """The main function to fetch and display all data."""
        self.load_button.configure(state=DISABLED, text="Loading...")
        self.update()

        user = self.user_var.get()
        start_date = self.start_date_entry.entry.get()
        end_date = self.end_date_entry.entry.get()

        if not user:
            self.load_button.configure(state=NORMAL, text="Load Data")
            return

        df = self.query_mongo_to_dataframe(user, start_date, end_date)

        if df.empty:
            self.total_time_var.set("--:--:--")
            self.idle_time_var.set("--:--:--")
            self.top_app_var.set("N/A")
            self.ax_bar.clear()
            self.ax_bar.text(0.5, 0.5, 'No Application Data', horizontalalignment='center', verticalalignment='center', color="#ffffff")
            self.canvas_bar.draw()
            self.ax_line.clear()
            self.ax_line.text(0.5, 0.5, 'No Data Available', horizontalalignment='center', verticalalignment='center', color="#ffffff")
            self.canvas_line.draw()
            self.load_button.configure(state=NORMAL, text="Load Data")
            return

        self.update_kpis(df)
        self.draw_app_usage_barchart(df)
        self.draw_daily_trends_linechart(df)
        self.load_button.configure(state=NORMAL, text="Load Data")

    def update_kpis(self, df):
        """Updates the top KPI cards with animation."""
        # FIX: Check if column exists, otherwise use 0
        total_idle_seconds = df['total_idle_seconds'].sum() if 'total_idle_seconds' in df.columns else 0

        app_seconds = 0
        all_apps = {}
        # FIX: Check if column exists before iterating
        if 'applications' in df.columns:
            for app_dict in df['applications']:
                if isinstance(app_dict, dict):
                    app_seconds += sum(app_dict.values())
                    for app, time in app_dict.items():
                        all_apps[app] = all_apps.get(app, 0) + time

        self.total_time_var.set(self.format_seconds(app_seconds))
        self.idle_time_var.set(self.format_seconds(total_idle_seconds))

        if all_apps:
            top_app = max(all_apps, key=all_apps.get).replace('_', '.')
            self.top_app_var.set(top_app)
        else:
            self.top_app_var.set("N/A")

    def draw_app_usage_barchart(self, df):
        """Draws the bar chart showing time per application."""
        self.ax_bar.clear()

        all_apps = {}
        # FIX: Check if column exists
        if 'applications' in df.columns:
            for app_dict in df['applications']:
                if isinstance(app_dict, dict):
                    for app, time in app_dict.items():
                        all_apps[app.replace('_', '.')] = all_apps.get(app.replace('_', '.'), 0) + time

        if not all_apps:
            self.ax_bar.text(0.5, 0.5, 'No Application Data', horizontalalignment='center', verticalalignment='center', color="#ffffff")
            self.canvas_bar.draw()
            return

        app_series = pd.Series(all_apps).sort_values(ascending=False).head(10)  # Top 10 apps

        sns.barplot(
            x=app_series.values / 3600,
            y=app_series.index,
            ax=self.ax_bar,
            palette="viridis",
            orient='h'
        )
        self.ax_bar.set_xlabel("Total Hours", color="#ffffff")
        self.ax_bar.set_ylabel("Application", color="#ffffff")
        self.ax_bar.set_title("Top 10 Most Used Applications", fontsize=11, color="#ffffff")
        self.ax_bar.tick_params(colors="#ffffff")
        self.fig_bar.tight_layout()
        self.canvas_bar.draw()

    def draw_daily_trends_linechart(self, df):
        """Draws the line chart showing productive vs. idle time."""
        self.ax_line.clear()

        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')

        # FIX: Check if columns exist, otherwise create them with 0
        if 'applications' not in df.columns:
            df['applications'] = [{} for _ in range(len(df))]
        if 'total_idle_seconds' not in df.columns:
            df['total_idle_seconds'] = 0


        df['productive_hours'] = df['applications'].apply(lambda x: sum(x.values()) / 3600 if isinstance(x, dict) else 0)
        df['idle_hours'] = df['total_idle_seconds'].fillna(0) / 3600 # fillna is an extra safety measure

        self.ax_line.plot(
            df['date'],
            df['productive_hours'],
            marker='o',
            linestyle='-',
            label='Productive Time',
            color='#00ff00'
        )
        self.ax_line.plot(
            df['date'],
            df['idle_hours'],
            marker='o',
            linestyle='--',
            label='Idle Time',
            color='#ff5555'
        )

        self.ax_line.set_xlabel("Date", color="#ffffff")
        self.ax_line.set_ylabel("Total Hours", color="#ffffff")
        self.ax_line.set_title("Productive vs. Idle Time", fontsize=11, color="#ffffff")
        self.ax_line.legend(facecolor="#333333", edgecolor="#444444", labelcolor="#ffffff")
        self.ax_line.tick_params(colors="#ffffff")
        self.ax_line.grid(True, linestyle='--', alpha=0.3)
        self.fig_line.autofmt_xdate()
        self.fig_line.tight_layout()
        self.canvas_line.draw()

if __name__ == "__main__":
    app = DashboardApp()
    app.mainloop()