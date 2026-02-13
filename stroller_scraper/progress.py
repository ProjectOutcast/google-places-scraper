import json
import os
from datetime import datetime


class ProgressTracker:
    CHECKPOINT_FILE = "scrape_checkpoint.json"

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.checkpoint_path = os.path.join(output_dir, self.CHECKPOINT_FILE)
        self.state = self._load_checkpoint()

    def _load_checkpoint(self) -> dict:
        if os.path.exists(self.checkpoint_path):
            with open(self.checkpoint_path, "r") as f:
                return json.load(f)
        return {
            "scraped_urls": {},
            "retailer_status": {},
            "started_at": datetime.now().isoformat(),
        }

    def _save_checkpoint(self):
        with open(self.checkpoint_path, "w") as f:
            json.dump(self.state, f, indent=2)

    def is_already_scraped(self, retailer: str, url: str) -> bool:
        return url in self.state["scraped_urls"].get(retailer, [])

    def mark_scraped(self, retailer: str, url: str):
        if retailer not in self.state["scraped_urls"]:
            self.state["scraped_urls"][retailer] = []
        self.state["scraped_urls"][retailer].append(url)
        self._save_checkpoint()

    def mark_retailer_done(self, retailer: str):
        self.state["retailer_status"][retailer] = "completed"
        self._save_checkpoint()

    def mark_retailer_failed(self, retailer: str, error: str):
        self.state["retailer_status"][retailer] = f"failed: {error}"
        self._save_checkpoint()

    def is_retailer_done(self, retailer: str) -> bool:
        return self.state["retailer_status"].get(retailer) == "completed"

    def update(self, retailer: str, current: int, total: int):
        pct = int((current / total) * 100) if total > 0 else 0
        print(f"  [{retailer}] {current}/{total} ({pct}%)")

    def reset(self):
        self.state = {
            "scraped_urls": {},
            "retailer_status": {},
            "started_at": datetime.now().isoformat(),
        }
        self._save_checkpoint()
