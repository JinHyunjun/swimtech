"""Windowless logon entry point. Enrollment is deliberately never automatic.

Task Scheduler owns restart-on-failure. The existing worker owns network retry,
credential renewal, and its per-service single-instance lock.
"""
from contextlib import redirect_stderr, redirect_stdout
import io
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys


class LogStream(io.TextIOBase):
    def __init__(self, logger):
        self.logger = logger
        self.pending = ''

    def write(self, value):
        self.pending += value
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            if line.strip(): self.logger.info(line.rstrip())
        if len(self.pending) > 4096: self.flush()
        return len(value)

    def flush(self):
        if self.pending:
            self.logger.info(self.pending)
            self.pending = ''


def run_saved_worker(run=None):
    """Exit zero on an intentional stop; unexpected failures request a restart."""
    try:
        if run is None:
            from .remote_worker import main as run
        run(['--saved-only'])
        return 0
    except Exception as exc:
        # Log only the exception class, never credentials or response bodies.
        print(f'Background processor stopped unexpectedly ({type(exc).__name__}). Windows will retry.', flush=True)
        return 1


def main():
    root = Path(os.environ.get('LOCALAPPDATA', Path.home()))/'SwimMate'/'video-worker'
    root.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('swimmate-background-worker')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(root/'background.log', maxBytes=1024*1024, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    logger.addHandler(handler)
    stream = LogStream(logger)
    try:
        with redirect_stdout(stream), redirect_stderr(stream):
            print('Windows automatic processor startup; restoring saved approval only.', flush=True)
            return run_saved_worker()
    finally:
        stream.flush()
        logger.removeHandler(handler)
        handler.close()


if __name__ == '__main__':
    sys.exit(main())
