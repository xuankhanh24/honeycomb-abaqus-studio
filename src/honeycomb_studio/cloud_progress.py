"""Bounded remote progress: checks each minute, catalog only at phase transitions."""

import threading
import time


class Progress:
    def __init__(self, github, catalog, identity, store, batch_id, deadline):
        self.github, self.catalog, self.identity = github, catalog, identity
        self.store, self.batch_id, self.deadline = store, batch_id, deadline
        self.done = threading.Event()
        self.check = None
        self.stop_reason = None
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def start(self, sha):
        self.check = self.github.repo(
            "POST",
            "/check-runs",
            {
                "name": "Honeycomb solver",
                "head_sha": sha,
                "status": "in_progress",
                "external_id": self.identity,
            },
        )["id"]
        self.thread.start()

    def stop_solver(self, reason="cancelled"):
        self.stop_reason = self.stop_reason or reason
        batch = self.store.get("batches", self.batch_id)
        batch.update(pause_requested=True, stop_immediately=True)
        self.store.save("batches", batch)

    def loop(self):
        previous = None
        while not self.done.is_set():
            # A GitHub outage must not disable the local solver deadline.
            if time.monotonic() >= self.deadline:
                self.stop_solver("timed_out")
            try:
                job, _ = self.catalog.get("jobs/" + self.identity)
                if (job or {}).get("cancel_requested"):
                    self.stop_solver()
                runs = self.store.list("runs", self.batch_id)
                active = next(
                    (r for r in runs if r["status"] not in ("completed", "review", "failed", "queued")), None
                )
                phase = active["status"] if active else "waiting"
                if phase != previous:
                    self.catalog.update("jobs/" + self.identity, lambda old: {**old, "phase": phase})
                    previous = phase
                self.github.repo(
                    "PATCH",
                    f"/check-runs/{self.check}",
                    {
                        "output": {
                            "title": "Phase: " + phase,
                            "summary": "Sequential licensed solver. Progress is observed, not predicted.",
                            "text": str((active or {}).get("progress", {}))[:10000],
                        }
                    },
                )
            except Exception:
                # A lost status update must not kill the actual solver or publish invented progress.
                pass
            self.done.wait(60)

    def finish(self, status):
        self.done.set()
        self.thread.join(timeout=35)
        if self.check:
            try:
                self.github.repo(
                    "PATCH",
                    f"/check-runs/{self.check}",
                    {
                        "status": "completed",
                        "conclusion": "success"
                        if status == "completed"
                        else "neutral"
                        if status == "review"
                        else "cancelled"
                        if status == "cancelled"
                        else "timed_out"
                        if status == "timed_out"
                        else "failure",
                        "output": {
                            "title": status,
                            "summary": "See the job catalog and release manifest for retained outputs.",
                        },
                    },
                )
            except Exception:
                pass
