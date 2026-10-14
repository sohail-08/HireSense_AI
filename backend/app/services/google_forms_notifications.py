"""Short-lived, in-process Sheets snapshots; never import applications or CVs."""
import time
from datetime import datetime, timezone
from threading import Lock


class SheetSnapshotCache:
    def __init__(self, clock=time.monotonic, ttl=60):
        self.clock, self.ttl = clock, ttl
        self.entries = {}
        self.lock = Lock()

    def read(self, key, load):
        # Serialize refreshes so multiple tabs do not multiply Sheets requests.
        with self.lock:
            now = self.clock()
            entry = self.entries.get(key)
            if entry and now < entry[0]:
                if entry[1] is None:
                    raise RuntimeError("Google response notifications are temporarily unavailable")
                return entry[1], entry[2]
            if len(self.entries) >= 32:
                self.entries.pop(next(iter(self.entries)))
            try:
                rows = load()
            except Exception:
                # Cool down failures as well; never cache/echo provider details.
                self.entries[key] = (self.clock() + self.ttl, None, None)
                raise RuntimeError("Google response notifications are temporarily unavailable") from None
            checked_at = datetime.now(timezone.utc)
            self.entries[key] = (self.clock() + self.ttl, rows, checked_at)
            return rows, checked_at


sheet_snapshots = SheetSnapshotCache()
