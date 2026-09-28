import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure


def hours_trend_figure(monthly_df):
    fig = Figure(figsize=(6, 3.2), dpi=100)
    ax = fig.add_subplot(111)
    if not monthly_df.empty:
        for name, grp in monthly_df.groupby("name"):
            grp = grp.sort_values("year_month")
            ax.plot(grp["year_month"], grp["total_hours"], marker="o", label=name)
        ax.legend(fontsize=7)
    ax.set_title("Total Hours per Month")
    ax.tick_params(axis="x", rotation=45, labelsize=7)
    fig.tight_layout()
    return fig


def excess_deficit_figure(monthly_df):
    fig = Figure(figsize=(6, 3.2), dpi=100)
    ax = fig.add_subplot(111)
    if not monthly_df.empty:
        latest = monthly_df["year_month"].max()
        data = monthly_df[monthly_df["year_month"] == latest]
        x = range(len(data))
        ax.bar(x, data["excess_hours"], width=0.35, label="Excess", color="#2ecc71")
        ax.bar([i + 0.35 for i in x], data["deficit_hours"], width=0.35, label="Deficit", color="#e74c3c")
        ax.set_xticks([i + 0.175 for i in x])
        ax.set_xticklabels(data["name"], rotation=45, ha="right", fontsize=7)
        ax.legend(fontsize=7)
        ax.set_title(f"Excess vs Deficit — {latest}")
    fig.tight_layout()
    return fig


def employee_hours_figure(emp_daily_df, name):
    fig = Figure(figsize=(6, 3), dpi=100)
    ax = fig.add_subplot(111)
    if not emp_daily_df.empty:
        ax.plot(emp_daily_df["date"], emp_daily_df["total_hours"], marker="o", color="#3498db")
    ax.set_title(f"Daily Hours — {name}")
    ax.tick_params(axis="x", rotation=45, labelsize=6)
    fig.tight_layout()
    return fig


def payroll_monthly_figure(monthly_payroll_df):
    fig = Figure(figsize=(6, 3.2), dpi=100)
    ax = fig.add_subplot(111)
    if not monthly_payroll_df.empty:
        latest = monthly_payroll_df["year_month"].max()
        data = monthly_payroll_df[monthly_payroll_df["year_month"] == latest]
        ax.bar(data["name"], data["total_pay"], color="#9b59b6")
        ax.set_xticklabels(data["name"], rotation=45, ha="right", fontsize=7)
        ax.set_title(f"Monthly Payroll — {latest}")
    fig.tight_layout()
    return fig
