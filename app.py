import os
import pandas as pd
from flask import Flask, render_template, request, send_file

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

OUTPUT_FILE = os.path.join(UPLOAD_FOLDER, "availability_results.xlsx")

TOTAL_TIME_MINUTES = 7 * 24 * 60  # 1 week


def duration_to_minutes(duration_str):
    """
    Converts '0 hours 10 minutes 2 seconds' → total minutes
    """
    try:
        h = m = s = 0
        parts = str(duration_str).lower().split()

        for i in range(0, len(parts), 2):
            value = int(parts[i])
            unit = parts[i + 1]

            if "hour" in unit:
                h = value
            elif "minute" in unit:
                m = value
            elif "second" in unit:
                s = value

        return h * 60 + m + (s / 60)
    except Exception:
        return None


def minutes_to_hms(total_minutes):
    total_seconds = int(total_minutes * 60)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours} hours {minutes} minutes {seconds} seconds"


@app.route("/")
def index():
    return render_template("upload.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    file = request.files.get("file")

    if not file or file.filename == "":
        return "No file selected"

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(filepath)

    # Load file
    ext = os.path.splitext(file.filename)[1].lower()
    try:
        if ext == ".csv":
            df = pd.read_csv(filepath, encoding="latin1", on_bad_lines="skip")
        elif ext in [".xls", ".xlsx"]:
            df = pd.read_excel(filepath)
        else:
            return "Unsupported file type"
    except Exception as e:
        return f"Error reading file: {e}"

    # Normalize column names
    df.rename(columns={
        "Alarm ID": "alarm_id",
        "Alarm Source": "alarm_source",
        "Duration": "duration"
    }, inplace=True)

    required_cols = {"alarm_id", "alarm_source", "duration"}
    if not required_cols.issubset(df.columns):
        return "Missing required columns (Alarm ID, Alarm Source, Duration)"

    # Clean data
    df["alarm_id"] = pd.to_numeric(df["alarm_id"], errors="coerce")
    df = df.dropna(subset=["alarm_id"])
    df["alarm_id"] = df["alarm_id"].astype(int)

    df["duration_minutes"] = df["duration"].apply(duration_to_minutes)
    df = df.dropna(subset=["duration_minutes"])

    # Filter
    df = df[(df["alarm_id"] == 100) & (df["duration_minutes"] >= 30)]

    if df.empty:
        return "No alarms found for Alarm ID 100 with duration >= 30 minutes."

    # ---- AGGREGATION (duplicates handled here) ----
    summary = (
        df.groupby("alarm_source", as_index=False)["duration_minutes"]
        .sum()
    )

    summary["Total Downtime"] = summary["duration_minutes"].apply(minutes_to_hms)

    summary["Availability (%)"] = (
        (TOTAL_TIME_MINUTES - summary["duration_minutes"])
        / TOTAL_TIME_MINUTES
    ) * 100

    summary["Availability (%)"] = summary["Availability (%)"].round(2)

    # Save Excel
    export_df = summary[["alarm_source", "Total Downtime", "Availability (%)"]]
    export_df.rename(columns={"alarm_source": "Alarm Source"}, inplace=True)
    export_df.to_excel(OUTPUT_FILE, index=False)

    # Prepare results for HTML
    results = []
    for _, row in summary.iterrows():
        results.append({
            "alarm_source": row["alarm_source"],
            "downtime": row["Total Downtime"],
            "availability": row["Availability (%)"]
        })

    return render_template("result.html", results=results)


@app.route("/download")
def download_file():
    if not os.path.exists(OUTPUT_FILE):
        return "No file available for download"
    return send_file(OUTPUT_FILE, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

