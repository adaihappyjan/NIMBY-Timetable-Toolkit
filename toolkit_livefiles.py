"""Cheap read-only file tracking. Never interprets a fresh pair as verified."""
import threading
import time


class StableFiles:
    def __init__(self, settle_seconds=3):
        self.settle_seconds = settle_seconds
        self.seen = {}
        self.lock = threading.Lock()

    def observe(self, files, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            result = {}; live = set()
            for group, rows in files.items():
                result[group] = []
                for row in rows:
                    key = row['path']; live.add(key)
                    signature = (row['size'], row['modified_ns'])
                    old = self.seen.get(key)
                    since = old[1] if old and old[0] == signature else now
                    self.seen[key] = (signature, since)
                    result[group].append({**row, 'stable': row['size'] > 0 and now-since >= self.settle_seconds})
            self.seen = {k:v for k,v in self.seen.items() if k in live}
            return result
