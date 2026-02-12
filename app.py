"""
Flask Web App for Google Places Scraper
========================================
Provides a web UI to configure and run the scraper with live progress.
"""

import os
import json
import uuid
import time
import hashlib
import threading
import glob as globmod
from datetime import datetime, timedelta

import requests as http_requests
from flask import Flask, render_template, request, jsonify, Response, send_file

from scraper import (
    run_scraper, export_to_excel, export_to_csv, get_summary,
    CATEGORY_PRESETS, DEFAULT_CATEGORIES,
)

app = Flask(__name__)

# ─── Job Storage (disk-backed) ───────────────────────────────────────────────

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# ─── Licensing (Lemon Squeezy) ───────────────────────────────────────────────

LS_API_KEY = os.environ.get("LEMON_SQUEEZY_API_KEY", "").strip()
LS_STORE_ID = os.environ.get("LEMON_SQUEEZY_STORE_ID", "").strip()
LS_CHECKOUT_URL = os.environ.get("LEMON_SQUEEZY_CHECKOUT_URL", "").strip()
LICENSE_CACHE_PATH = os.path.join(TEMP_DIR, "license_cache.json")
LICENSE_CACHE_TTL_HOURS = 72


def is_licensing_enabled():
    return bool(LS_API_KEY and LS_STORE_ID and LS_CHECKOUT_URL)


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.strip().encode()).hexdigest()


def _load_license_cache() -> dict:
    if not os.path.exists(LICENSE_CACHE_PATH):
        return {}
    try:
        with open(LICENSE_CACHE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_license_cache(cache: dict):
    try:
        with open(LICENSE_CACHE_PATH, "w") as f:
            json.dump(cache, f)
    except OSError:
        pass


def _check_cache(key_hash: str):
    """Check if key is in cache and still valid. Returns True/False/None (not found)."""
    cache = _load_license_cache()
    entry = cache.get(key_hash)
    if not entry:
        return None
    last_checked = datetime.fromisoformat(entry.get("last_checked", "2000-01-01"))
    if datetime.now() - last_checked > timedelta(hours=LICENSE_CACHE_TTL_HOURS):
        return None  # Expired, needs re-validation
    return entry.get("valid", False)


def _cache_license(key_hash: str, valid: bool):
    cache = _load_license_cache()
    cache[key_hash] = {
        "valid": valid,
        "last_checked": datetime.now().isoformat(),
    }
    _save_license_cache(cache)


def _validate_with_ls(license_key: str) -> tuple:
    """
    Validate a license key with Lemon Squeezy API.
    Returns (valid: bool, error_message: str).
    """
    # Try activation first
    try:
        resp = http_requests.post(
            "https://api.lemonsqueezy.com/v1/licenses/activate",
            json={
                "license_key": license_key,
                "instance_name": "scraper",
            },
            headers={
                "Accept": "application/json",
            },
            timeout=15,
        )
        data = resp.json()

        if data.get("activated") or data.get("valid"):
            # Verify store
            meta = data.get("meta", {})
            store_id = str(meta.get("store_id", ""))
            if LS_STORE_ID and store_id and store_id != LS_STORE_ID:
                return False, "License key does not belong to this product."
            return True, ""

        error = data.get("error", "")
        # If already activated on this instance, try validate
        if "already" in str(error).lower() or resp.status_code == 422:
            resp2 = http_requests.post(
                "https://api.lemonsqueezy.com/v1/licenses/validate",
                json={
                    "license_key": license_key,
                    "instance_name": "scraper",
                },
                headers={
                    "Accept": "application/json",
                },
                timeout=15,
            )
            data2 = resp2.json()
            if data2.get("valid"):
                meta2 = data2.get("meta", {})
                store_id2 = str(meta2.get("store_id", ""))
                if LS_STORE_ID and store_id2 and store_id2 != LS_STORE_ID:
                    return False, "License key does not belong to this product."
                return True, ""
            return False, data2.get("error", "Invalid license key.")

        return False, data.get("error", "Invalid license key.")

    except http_requests.RequestException:
        # LS API is down — check cache as grace period
        key_hash = _hash_key(license_key)
        cache = _load_license_cache()
        entry = cache.get(key_hash)
        if entry and entry.get("valid"):
            return True, ""  # Grace: let them through
        return False, "Unable to verify license. Please try again later."


def validate_license(license_key: str) -> tuple:
    """
    Full license validation flow: cache check → LS API → cache result.
    Returns (valid: bool, error: str).
    """
    if not license_key or not license_key.strip():
        return False, "License key is required."

    key_hash = _hash_key(license_key)

    # Check cache first
    cached = _check_cache(key_hash)
    if cached is True:
        return True, ""
    if cached is False:
        return False, "License key is invalid or expired."

    # Not in cache or expired — call LS API
    valid, error = _validate_with_ls(license_key)
    _cache_license(key_hash, valid)
    return valid, error


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


@app.route("/api/license-config")
def license_config():
    """Return licensing configuration for the frontend."""
    return jsonify({
        "enabled": is_licensing_enabled(),
        "checkout_url": LS_CHECKOUT_URL if is_licensing_enabled() else "",
    })


@app.route("/api/validate-license", methods=["POST"])
def validate_license_route():
    """Validate a license key."""
    data = request.get_json()
    if not data:
        return jsonify({"valid": False, "error": "No data provided"}), 400

    license_key = data.get("license_key", "").strip()
    valid, error = validate_license(license_key)

    if valid:
        return jsonify({"valid": True})
    return jsonify({"valid": False, "error": error})


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

    # License check (server-side guard)
    if is_licensing_enabled():
        license_key = data.get("license_key", "").strip()
        valid, error = validate_license(license_key)
        if not valid:
            return jsonify({"error": "Invalid or missing license key. Please activate your license."}), 403

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


# ─── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
