"""A per-run downloader view: bulk selection must not poll the full queue per item."""

from typing import Any


class BatchTorrentView:
    """Cache one baseline during a batch; the caller reconciles one fresh snapshot after it.

    Command responses still come from the real adapter. Confirmed removals and
    pauses update this local view so later decisions cannot see stale commands.
    """

    def __init__(self, instance: Any):
        self._instance = instance
        self._rows = None
        self._failed = False

    def get_torrents(self, *args, **kwargs):
        if self._rows is None:
            rows, failed = self._instance.get_torrents()
            self._rows = [dict(row) for row in rows or []]
            self._failed = bool(failed)
        return list(self._rows), self._failed

    def __getattr__(self, name: str):
        value = getattr(self._instance, name)
        if name not in {"delete_torrents", "pause_torrents", "resume_torrents"} or not callable(value):
            return value

        def invoke(*args, **kwargs):
            result = value(*args, **kwargs)
            if result and self._rows is not None:
                ids = kwargs.get("ids", args[0] if args else [])
                ids = {str(key).lower() for key in ids}
                if name == "delete_torrents":
                    self._rows = [row for row in self._rows if str(row.get("hash") or "").lower() not in ids]
                else:
                    for row in self._rows:
                        if str(row.get("hash") or "").lower() in ids:
                            row["state"] = "pausedDL" if name == "pause_torrents" else "downloading"
            return result
        return invoke
