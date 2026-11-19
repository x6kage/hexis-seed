"""Offline tests for hooks/guard.py: the macOS teardown commands are denied in every permission mode, and the
commands next to them that tear nothing down pass."""

import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[2] / "hooks"
sys.path.insert(0, str(HOOKS))
import _common


def load(path, name):
    run, _common.run = _common.run, lambda n, f: None
    stdin, sys.stdin = sys.stdin, io.TextIOWrapper(io.BytesIO())
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        _common.run, sys.stdin = run, stdin


guard = load(HOOKS / "guard.py", "guard")


def decide(command, mode="bypassPermissions"):
    out = guard.main({"tool_name": "Bash", "tool_input": {"command": command}, "permission_mode": mode})
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else None


class MacTeardown(unittest.TestCase):
    def test_each_teardown_is_denied_in_every_mode(self):
        commands = [
            "launchctl unload ~/Library/LaunchAgents/com.example.agent.plist",
            "sudo launchctl bootout system/com.example.daemon",
            "launchctl bootout gui/501/com.example.agent",
            "launchctl remove com.example.agent",
            "launchctl disable gui/501/com.example.agent",
            "killall Finder",
            "killall -9 Dock",
            "killall SystemUIServer",
            "sudo killall -HUP WindowServer",
            "reboot",
            "sudo reboot",
            "cd /tmp && sudo reboot",
            "sudo shutdown -h now",
            "brew uninstall --cask some-app",
            "rm ~/Library/LaunchAgents/com.example.agent.plist",
            "rm -f /Library/LaunchAgents/com.example.agent.plist",
            "unlink ~/Library/LaunchAgents/com.example.agent.plist",
        ]
        for command in commands:
            for mode in ("bypassPermissions", "default", "acceptEdits"):
                with self.subTest(command=command, mode=mode):
                    self.assertEqual(decide(command, mode), "deny")

    def test_near_misses_pass(self):
        commands = [
            "launchctl list",
            "launchctl print gui/501/com.example.agent",
            "launchctl load ~/Library/LaunchAgents/com.example.agent.plist",
            "killall node",
            "pgrep -l Dock",
            "echo reboot later",
            "git commit -m 'note why a reboot helped' -- notes.md",
            "man shutdown",
            "brew upgrade --cask some-app",
            "brew install --cask some-app",
            "ls ~/Library/LaunchAgents/",
            "cat ~/Library/LaunchAgents/com.example.agent.plist",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(decide(command))


if __name__ == "__main__":
    unittest.main()
