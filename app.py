"""
Flask Web App for Google Places Scraper
========================================
Provides a web UI to configure and run the scraper with live progress.
"""

import os
import json
import uuid
import time
import threading
import shutil
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify, Response, send_file

from scraper import (
    run_scraper, export_to_excel, get_summary,
    CATEGORY_PRESETS, DEFAULT_CATEGORIES,
)

app = Flask(__name__)

# ─── Job Storage ─────────────────────────────────────────────────────────────

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# In-memory job store: {job_id: {...}}
jobs = {}
jobs_lock = threading.Lock()

JOB_EXPIRY_HOURS = 1


# ─── Cleanup ─────────────────────────────────────────────────────────────────

def cleanup_old_jobs():
    """Remove expired jobs and their files."""
    now = datetime.now()
    with jobs_lock:
        expired = [
            jid for jid, job in jobs.items()
            if now - job.get("created_at", now) > timedelta(hours=JOB_EXPIRY_HOURS)
        ]
        for jid in expired:
            filepath = jobs[jid].get("filepath")
            if filepath and os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            del jobs[jid]


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template(
        "index.html",
        category_presets=CATEGORY_PRESETS,
        default_categories=DEFAULT_CATEGORIES,
    )


@app.route("/api/presets")
def get_presets():
    """Return category presets as JSON."""
    return jsonify({
        "presets": {
            name: {
                "queries": [q["query"] for q in queries],
                "category": queries[0]["category"] if queries else name.title(),
            }
            for name, queries in CATEGORY_PRESETS.items()
        },
        "defaults": DEFAULT_CATEGORIES,
    })


@app.route("/api/scrape", methods=["POST"])
def start_scrape():
    """Start a new scraping job."""
    cleanup_old_jobs()

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    api_key = data.get("api_key", "").strip()
    location = data.get("location", "").strip()
    radius = data.get("radius", 3000)
    categories = data.get("categories", [])
    custom_queries = data.get("custom_queries", "").strip()

    # Validation
    if not api_key:
        return jsonify({"error": "Google API key is required"}), 400
    if not location:
        return jsonify({"error": "Location is required"}), 400
    if not categories and not custom_queries:
        return jsonify({"error": "Select at least one category or enter custom queries"}), 400

    # Merge categories with custom queries
    all_categories = list(categories)
    if custom_queries:
        custom = [q.strip() for q in custom_queries.split(",") if q.strip()]
        all_categories.extend(custom)

    # Create job
    job_id = str(uuid.uuid4())[:8]
    job = {
        "id": job_id,
        "status": "running",
        "progress": 0,
        "messages": [],
        "summary": None,
        "filepath": None,
        "error": None,
        "created_at": datetime.now(),
    }

    with jobs_lock:
        jobs[job_id] = job

    # Run scraper in background thread
    thread = threading.Thread(
        target=_run_scrape_job,
        args=(job_id, api_key, location, all_categories, radius),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


def _run_scrape_job(job_id, api_key, location, categories, radius):
    """Background thread: runs the scraper and updates the job."""

    def progress_callback(message, percent=None):
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["messages"].append(message)
                if percent is not None:
                    jobs[job_id]["progress"] = percent

    try:
        businesses = run_scraper(
            api_key=api_key,
            location=location,
            categories=categories,
            radius=radius,
            progress_callback=progress_callback,
        )

        if businesses:
            # Generate Excel file
            from scraper import slugify
            filename = f"{slugify(location)}_businesses.xlsx"
            filepath = os.path.join(TEMP_DIR, f"{job_id}_{filename}")
            export_to_excel(businesses, filepath)
            summary = get_summary(businesses)

            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]["status"] = "completed"
                    jobs[job_id]["progress"] = 100
                    jobs[job_id]["filepath"] = filepath
                    jobs[job_id]["filename"] = filename
                    jobs[job_id]["summary"] = summary
                    jobs[job_id]["messages"].append(
                        f"Exported {len(businesses)} businesses to Excel."
                    )
        else:
            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]["status"] = "completed"
                    jobs[job_id]["progress"] = 100
                    jobs[job_id]["summary"] = {"total": 0, "by_category": {}, "avg_rating": None, "rated_count": 0, "top5": []}
                    jobs[job_id]["messages"].append("No businesses found.")

    except Exception as e:
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = str(e)
                jobs[job_id]["messages"].append(f"Error: {e}")


@app.route("/api/progress/<job_id>")
def stream_progress(job_id):
    """SSE endpoint: streams progress updates to the client."""

    def generate():
        last_msg_idx = 0
        last_progress = -1

        while True:
            with jobs_lock:
                job = jobs.get(job_id)

            if not job:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Job not found'})}\n\n"
                break

            # Send new messages
            messages = job.get("messages", [])
            while last_msg_idx < len(messages):
                msg = messages[last_msg_idx]
                last_msg_idx += 1
                yield f"data: {json.dumps({'type': 'log', 'message': msg})}\n\n"

            # Send progress update
            progress = job.get("progress", 0)
            if progress != last_progress:
                last_progress = progress
                yield f"data: {json.dumps({'type': 'progress', 'percent': progress})}\n\n"

            # Check completion
            status = job.get("status")
            if status == "completed":
                result = {
                    "type": "completed",
                    "summary": job.get("summary"),
                    "has_file": job.get("filepath") is not None,
                }
                yield f"data: {json.dumps(result)}\n\n"
                break
            elif status == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': job.get('error', 'Unknown error')})}\n\n"
                break

            time.sleep(0.5)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/download/<job_id>")
def download_file(job_id):
    """Download the generated Excel file."""
    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        return jsonify({"error": "Job not found"}), 404

    filepath = job.get("filepath")
    filename = job.get("filename", "businesses.xlsx")

    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    return send_file(
        filepath,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ─── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
