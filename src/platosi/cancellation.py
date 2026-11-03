"""Cooperative cancellation for local model requests."""

import threading


class Cancelled(Exception):
    pass


class Cancellation:
    def __init__(self):
        self.event = threading.Event()

    def check(self):
        if self.event.is_set():
            raise Cancelled("Generation stopped")

    def cancel(self):
        self.event.set()
