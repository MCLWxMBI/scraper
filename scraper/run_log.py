"""Incremental text-mode transcript of Python terminal output."""

import sys
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from uuid import uuid4

from scraper.config import PROJECT_DIR

RUN_LOG_DIR = PROJECT_DIR / 'output' / 'logs'


class RunLogError(RuntimeError):
    """A transcript could not be saved; stop without retrying broken logging."""


class _Tee:
    def __init__(self, original, transcript):
        self.original = original
        self.transcript = transcript

    def write(self, text):
        self.original.write(text)
        self.transcript.write(text)
        return len(text)

    def flush(self):
        self.original.flush()
        self.transcript.flush()

    def __getattr__(self, name):
        return getattr(self.original, name)


class RunTranscript:
    def __init__(self):
        self.run_id = uuid4().hex
        self.path = RUN_LOG_DIR / f'{self.run_id}.txt'
        self.failed = False

    def __enter__(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.file = self.path.open('x', encoding='utf-8', newline='\n')
        except (OSError, UnicodeError):
            raise RunLogError('Cannot open text-mode run log.') from None
        self.streams = ExitStack()
        try:
            self.streams.enter_context(redirect_stdout(_Tee(sys.stdout, self)))
            self.streams.enter_context(redirect_stderr(_Tee(sys.stderr, self)))
        except BaseException:
            self.streams.close()
            self.file.close()
            raise
        return self

    def write(self, text):
        if self.failed:
            raise RunLogError('Cannot write text-mode run log.')
        try:
            self.file.write(text)
            self.file.flush()
        except (OSError, UnicodeError):
            self.failed = True
            raise RunLogError('Cannot write text-mode run log.') from None

    def flush(self):
        if self.failed:
            raise RunLogError('Cannot write text-mode run log.')
        try:
            self.file.flush()
        except (OSError, UnicodeError):
            self.failed = True
            raise RunLogError('Cannot write text-mode run log.') from None

    def __exit__(self, *args):
        # Restore the real streams before close or error handling can print.
        self.streams.close()
        try:
            self.file.close()
        except (OSError, UnicodeError):
            raise RunLogError('Cannot close text-mode run log.') from None
