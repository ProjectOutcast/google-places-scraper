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
import glob as globmod
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify, Response, send_file

from scraper import (
    run_scraper, export_to_excel, export_to_csv, get_summary,
    CATEGORY_PRESETS, DEFAULT_CATEGORIES,
    PRIMARY_CATEGORIES, SECONDARY_CATEGORIES,
)

import sys
import asyncio
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "stroller_scraper"))
from stroller_scraper.retailers import get_scraper_registry
from stroller_scraper.main import run_all_scrapers as run_product_scrapers
from stroller_scraper.exporter import export_combined_csv

app = Flask(__name__)

# ─── Job Storage (disk-backed) ───────────────────────────────────────────────

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# In-memory store for RUNNING jobs (progress/messages). Completed jobs are on disk.
jobs = {}
jobs_lock = threading.Lock()

JOB_EXPIRY_HOURS = 2


def _job_meta_path(job_id):
    return os.path.join(TEMP_DIR, f"{job_id}_meta.json")


def _save_job_meta(job_id, meta):
    """Save job metadata to disk so it survives server restarts."""
    path = _job_meta_path(job_id)
    # Make a serializable copy
    safe = {k: v for k, v in meta.items() if k != "created_at"}
    safe["created_at"] = meta.get("created_at", datetime.now()).isoformat()
    with open(path, "w") as f:
        json.dump(safe, f)


def _load_job_meta(job_id):
    """Load job metadata from disk."""
    path = _job_meta_path(job_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            meta = json.load(f)
        meta["created_at"] = datetime.fromisoformat(meta["created_at"])
        return meta
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def _get_job(job_id):
    """Get a job from memory (if running) or disk (if completed)."""
    with jobs_lock:
        job = jobs.get(job_id)
    if job:
        return job
    # Try loading from disk (completed job)
    return _load_job_meta(job_id)


# ─── Cleanup ─────────────────────────────────────────────────────────────

def cleanup_old_jobs():
    """Remove expired jobs and their files."""
    now = datetime.now()
    cutoff = now - timedelta(hours=JOB_EXPIRY_HOURS)

    # Clean in-memory jobs
    with jobs_lock:
        expired = [
            jid for jid, job in jobs.items()
            if job.get("created_at", now) < cutoff
        ]
        for jid in expired:
            del jobs[jid]

    # Clean disk files older than expiry
    for meta_file in globmod.glob(os.path.join(TEMP_DIR, "*_meta.json")):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(meta_file))
            if mtime < cutoff:
                job_id = os.path.basename(meta_file).replace("_meta.json", "")
                # Remove meta file
                os.remove(meta_file)
                # Remove associated xlsx files
                for f in globmod.glob(os.path.join(TEMP_DIR, f"{job_id}_*")):
                    os.remove(f)
        except OSError:
            pass


# ─── Routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template(
        "index.html",
        category_presets=CATEGORY_PRESETS,
        default_categories=DEFAULT_CATEGORIES,
    )


@app.route("/api/presets")
def get_presets():
    """Return category presets as JSON with primary/secondary tiers."""
    return jsonify({
        "presets": {
            name: {
                "queries": [q["query"] for q in queries],
                "category": queries[0]["category"] if queries else name.title(),
            }
            for name, queries in CATEGORY_PRESETS.items()
        },
        "defaults": DEFAULT_CATEGORIES,
        "primary": PRIMARY_CATEGORIES,
        "secondary": SECONDARY_CATEGORIES,
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
        "filename": None,
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
            # Generate Excel + CSV files
            from scraper import slugify
            base_name = slugify(location) + "_businesses"
            xlsx_filename = f"{base_name}.xlsx"
            csv_filename = f"{base_name}.csv"
            xlsx_path = os.path.join(TEMP_DIR, f"{job_id}_{xlsx_filename}")
            csv_path = os.path.join(TEMP_DIR, f"{job_id}_{csv_filename}")
            export_to_excel(businesses, xlsx_path)
            export_to_csv(businesses, csv_path)
            summary = get_summary(businesses)

            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]["status"] = "completed"
                    jobs[job_id]["progress"] = 100
                    jobs[job_id]["filepath"] = xlsx_path
                    jobs[job_id]["filename"] = xlsx_filename
                    jobs[job_id]["csv_filepath"] = csv_path
                    jobs[job_id]["csv_filename"] = csv_filename
                    jobs[job_id]["summary"] = summary
                    jobs[job_id]["messages"].append(
                        f"Exported {len(businesses)} businesses to Excel & CSV."
                    )
                    _save_job_meta(job_id, jobs[job_id])
        else:
            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]["status"] = "completed"
                    jobs[job_id]["progress"] = 100
                    jobs[job_id]["summary"] = {"total": 0, "by_category": {}, "avg_rating": None, "rated_count": 0, "top5": []}
                    jobs[job_id]["messages"].append("No businesses found.")
                    _save_job_meta(job_id, jobs[job_id])

    except Exception as e:
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = str(e)
                jobs[job_id]["messages"].append(f"Error: {e}")
                _save_job_meta(job_id, jobs[job_id])


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
    """Download the generated file. Use ?format=csv for CSV."""
    job = _get_job(job_id)

    if not job:
        return jsonify({"error": "Job not found. The file may have expired (files are kept for 2 hours)."}), 404

    fmt = request.args.get("format", "xlsx")

    if fmt == "csv":
        filepath = job.get("csv_filepath")
        filename = job.get("csv_filename", "businesses.csv")
        mimetype = "text/csv"
    else:
        filepath = job.get("filepath")
        filename = job.get("filename", "businesses.xlsx")
        mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found. It may have been cleaned up. Please run the scrape again."}), 404

    return send_file(filepath, as_attachment=True, download_name=filename, mimetype=mimetype)


# ─── Product Scraper Routes ───────────────────────────────────────────────

@app.route("/scraper")
def scraper_page():
    return render_template("scraper.html")


@app.route("/api/retailers")
def get_retailers():
    return jsonify({"retailers": sorted(get_scraper_registry().keys())})


@app.route("/api/product-scrape", methods=["POST"])
def start_product_scrape():
    cleanup_old_jobs()

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    keyword = data.get("keyword", "").strip()
    retailers = data.get("retailers", [])

    if not keyword:
        return jsonify({"error": "Keyword is required"}), 400
    if not retailers:
        return jsonify({"error": "Select at least one retailer"}), 400

    job_id = str(uuid.uuid4())[:8]
    job = {
        "id": job_id,
        "status": "running",
        "progress": 0,
        "messages": [],
        "summary": None,
        "filepath": None,
        "filename": None,
        "csv_filepath": None,
        "csv_filename": None,
        "error": None,
        "created_at": datetime.now(),
    }

    with jobs_lock:
        jobs[job_id] = job

    thread = threading.Thread(
        target=_run_product_scrape_job,
        args=(job_id, keyword, retailers),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


def _run_product_scrape_job(job_id, keyword, retailers):
    def progress_callback(message, percent=None):
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["messages"].append(message)
                if percent is not None:
                    jobs[job_id]["progress"] = percent

    try:
        output_dir = os.path.join(TEMP_DIR, job_id)
        os.makedirs(output_dir, exist_ok=True)

        products = asyncio.run(
            run_product_scrapers(
                retailers=retailers,
                headless=True,
                resume=False,
                output_dir=output_dir,
                keyword=keyword,
                progress_callback=progress_callback,
            )
        )

        if products:
            csv_filename = f"{keyword.replace(' ', '_')}_products.csv"
            csv_path = os.path.join(TEMP_DIR, f"{job_id}_{csv_filename}")
            export_combined_csv(products, csv_path)

            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]["status"] = "completed"
                    jobs[job_id]["progress"] = 100
                    jobs[job_id]["csv_filepath"] = csv_path
                    jobs[job_id]["csv_filename"] = csv_filename
                    jobs[job_id]["summary"] = {"total": len(products)}
                    jobs[job_id]["messages"].append(
                        f"Done! Exported {len(products)} products to CSV."
                    )
                    _save_job_meta(job_id, jobs[job_id])
        else:
            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]["status"] = "completed"
                    jobs[job_id]["progress"] = 100
                    jobs[job_id]["summary"] = {"total": 0}
                    jobs[job_id]["messages"].append("No products found.")
                    _save_job_meta(job_id, jobs[job_id])

    except Exception as e:
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = str(e)
                jobs[job_id]["messages"].append(f"Error: {e}")
                _save_job_meta(job_id, jobs[job_id])


# ─── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
