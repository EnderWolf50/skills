"""Fakes shared by the tests: a command router standing in for git, glab and gh, and a config writer."""
import json

import pytest


def ok(body):
    return (0, json.dumps(body), "")


class Fake:
    """Answers each command from the first route whose key is a substring of it (a key starting with `=` must match the
    whole command); a list answers in turn, its last item repeating."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, cmd):
        line = " ".join(cmd)
        self.calls.append(line)
        for key, answer in self.routes.items():
            if (line == key[1:]) if key.startswith("=") else (key in line):
                if isinstance(answer, list):
                    return answer.pop(0) if len(answer) > 1 else answer[0]
                return answer
        raise AssertionError(f"unexpected command: {line}")

    def writes(self):
        return [c for c in self.calls if " -X " in c]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.fixture
def config(tmp_path):
    """Write a config file and return its path; the state directory is tmp_path/state."""

    def write(text=""):
        path = tmp_path / "project.toml"
        state = (tmp_path / "state").as_posix()
        path.write_text(f'state_dir = "{state}"\n{text}', encoding="utf-8")
        return str(path)

    return write
