from robot_framework.email import EmailStatus


class FakeEmailAdapter:
    """No network or authentication. Success is explicitly simulated, never delivered."""
    def __init__(self, status=EmailStatus.SIMULATED):
        self.status = EmailStatus(status)
        self.calls = 0

    def send(self, message, *, timeout_seconds):
        self.calls += 1
        return self.status
