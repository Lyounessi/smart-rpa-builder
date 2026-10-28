import os
import re


class EnvironmentSecrets:
    """Local milestone provider. Replace with a vault without changing robot code."""
    def get(self, name):
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*', name):
            raise ValueError('Invalid secret reference.')
        value = os.environ.get('RPA_SECRET_' + name)
        if value is None:
            raise RuntimeError('Required secret is unavailable.')
        return value
