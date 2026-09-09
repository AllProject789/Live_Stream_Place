"""Shared logging: timestamped console output plus a per-script log file.

Every script logs to both the terminal and `data/<name>.log`, so a run that
looked fine on screen can still be inspected afterwards. Long loops report
through Progress(), which prints a rate and an ETA — the pipeline steps take
minutes, and "500/1054" alone does not say whether that is good or stuck.
"""
import logging
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "data")


def setup(name, level=logging.INFO):
    """Return a logger writing to the console and data/<name>.log."""
    log = logging.getLogger(name)
    if log.handlers:                       # already configured (re-import)
        return log
    log.setLevel(level)
    fmt = logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    log.addHandler(console)

    os.makedirs(LOG_DIR, exist_ok=True)
    to_file = logging.FileHandler(os.path.join(LOG_DIR, name + ".log"), encoding="utf-8")
    to_file.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(to_file)
    return log


def human(seconds):
    """42 -> '42s', 145 -> '2m25s', 4000 -> '1h6m'."""
    seconds = int(max(seconds, 0))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{seconds % 3600 // 60}m"


class Progress:
    """Progress reporter for a long loop.

    Logs at most one line per `every` items, with percentage, rate and ETA:
        600/1054   57%   9.4/s   eta 48s   resolved=495 skipped=105
    """

    def __init__(self, total, log, label="", every=100):
        self.total = max(total, 1)
        self.log = log
        self.label = label
        self.every = max(every, 1)
        self.done = 0
        self.started = time.monotonic()

    def tick(self, n=1, extra=""):
        self.done += n
        if self.done % self.every and self.done != self.total:
            return
        self.report(extra)

    def report(self, extra=""):
        elapsed = time.monotonic() - self.started
        rate = self.done / elapsed if elapsed > 0 else 0
        eta = (self.total - self.done) / rate if rate > 0 else 0
        head = f"  {self.label + ' ' if self.label else ''}{self.done}/{self.total}"
        self.log.info(f"{head}  {100 * self.done // self.total:3d}%  "
                      f"{rate:5.1f}/s  eta {human(eta):>6}"
                      f"{'  ' + extra if extra else ''}")

    def finish(self, extra=""):
        elapsed = time.monotonic() - self.started
        self.log.info(f"  {self.label or 'done'}: {self.done}/{self.total} in "
                      f"{human(elapsed)}{'  ' + extra if extra else ''}")
