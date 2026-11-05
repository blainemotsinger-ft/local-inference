"""Tests for the Claude Code scripts, run against tests/fake_colibri.py.

    python3 -m unittest discover -s tests -v

No model, GPU, or network is needed. The tests that start Claude Code need
`claude` on PATH and are skipped without it. Each test gets its own git
repository and its own CLAUDE_CONFIG_DIR, so nothing touches your ~/.claude.
"""

import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path

from fake_colibri import MODEL_ID, FakeColibri, text, tool

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "scripts" / "claude-local-worker.sh"
SESSION = ROOT / "scripts" / "claude-colibri.sh"
BOOTSTRAP = ROOT / "scripts" / "bootstrap-claude.sh"
ENV_FILE = ROOT / "scripts" / "colibri-claude-env.sh"
WORKER_PROMPT_START = "You are a coding worker running on a local model."
WORKER_TOOLS = {"Read", "Edit", "Write", "Glob", "Grep", "Bash"}

HAVE_CLAUDE = shutil.which("claude") is not None
needs_claude = unittest.skipUnless(HAVE_CLAUDE, "claude is not on PATH")

# Variables from the caller's shell that would change what the scripts do.
SCRUB = ("ANTHROPIC_", "CLAUDE_CODE_", "COLIBRI_", "CLAUDECODE", "API_TIMEOUT_MS")


def free_port():
    """A port with nothing listening on it."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Sandbox(unittest.TestCase):
    """A throwaway git repository and Claude Code config folder."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="local-inference-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        self.config = self.tmp / "claude-config"
        self.repo.mkdir()
        self.config.mkdir()
        (self.repo / "keep.txt").write_text("keep me\n")
        self.git("init", "-q")
        self.git("add", "keep.txt")
        self.git("commit", "-q", "-m", "init")

    def git(self, *args):
        return subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
            cwd=self.repo, check=True, capture_output=True, text=True,
        ).stdout

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith(SCRUB)}
        env["CLAUDE_CONFIG_DIR"] = str(self.config)
        env.update(extra)
        return env

    def run_script(self, script, *args, **env):
        return subprocess.run(
            [str(script), *args], cwd=self.repo, env=self.env(**env),
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180,
        )

    def assertRan(self, result):
        self.assertEqual(result.returncode, 0, f"exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")


@needs_claude
class WorkerPermissions(Sandbox):
    def test_dangerous_commands_are_denied(self):
        commands = [
            "git push origin main",
            "git commit --allow-empty -m sneaky",
            "git rebase HEAD",
            "rm keep.txt",
            "cd . && git commit --allow-empty -m hidden",
        ]
        script = [tool("Bash", command=c, description="try it") for c in commands] + [text("done")]
        with FakeColibri(script) as fake:
            result = self.run_script(WORKER, "try the blocked commands", COLIBRI_BASE_URL=fake.base_url)
        self.assertRan(result)
        results = fake.tool_results()
        self.assertEqual(len(results), len(commands), results)
        for command, outcome in zip(commands, results):
            self.assertIn("denied", outcome.lower(), f"{command!r} was not denied: {outcome}")
        self.assertEqual(self.git("rev-list", "--count", "HEAD").strip(), "1", "a commit got through")
        self.assertTrue((self.repo / "keep.txt").exists(), "rm got through")

    def test_file_tools_work(self):
        script = [
            tool("Write", file_path="new.txt", content="alpha\n"),
            tool("Edit", file_path="new.txt", old_string="alpha", new_string="beta"),
            tool("Glob", pattern="*.txt"),
            tool("Grep", pattern="beta", output_mode="files_with_matches"),
            tool("Bash", command="cat new.txt", description="show the file"),
            text("done: new.txt says beta"),
        ]
        with FakeColibri(script) as fake:
            result = self.run_script(WORKER, "make new.txt", COLIBRI_BASE_URL=fake.base_url)
        self.assertRan(result)
        self.assertEqual((self.repo / "new.txt").read_text(), "beta\n")
        results = fake.tool_results()
        self.assertEqual(len(results), 5, results)
        for outcome in results:
            self.assertNotIn("denied", outcome.lower(), outcome)
        self.assertIn("new.txt", results[2], "Glob did not find the file")
        self.assertIn("new.txt", results[3], "Grep did not find the file")
        self.assertIn("beta", results[4], "Bash did not run")
        self.assertIn("done: new.txt says beta", result.stdout)


@needs_claude
class WorkerRequests(Sandbox):
    def test_request_shape(self):
        task = """--help "double" 'single' $HOME `date` \\ end"""
        with FakeColibri([text("done")]) as fake:
            result = self.run_script(WORKER, task, COLIBRI_BASE_URL=fake.base_url)
        self.assertRan(result)

        reqs = fake.messages_requests()
        self.assertTrue(reqs, "no /v1/messages request reached the server")
        for r in reqs:
            self.assertEqual(r["body"]["model"], MODEL_ID)
            self.assertEqual(r["headers"].get("x-api-key"), "local")
            self.assertNotIn("authorization", r["headers"])

        first = reqs[0]["body"]
        tools = {t["name"] for t in first.get("tools", [])}
        self.assertLessEqual(WORKER_TOOLS, tools, f"missing tools: {WORKER_TOOLS - tools}")
        for unwanted in ("WebFetch", "WebSearch", "Agent", "Task"):
            self.assertNotIn(unwanted, tools)
        system = str(first.get("system"))
        self.assertIn(WORKER_PROMPT_START, system)
        self.assertIn(task, fake.first_user_text(), "the task did not arrive unchanged")

    def test_runs_from_inside_claude_code(self):
        # What /farm looks like: started from a Claude Code session that is
        # logged in with its own credentials.
        with FakeColibri([text("done")]) as fake:
            result = self.run_script(
                WORKER, "say done",
                COLIBRI_BASE_URL=fake.base_url,
                CLAUDECODE="1",
                ANTHROPIC_API_KEY="the-lead-sessions-real-key",
                ANTHROPIC_AUTH_TOKEN="the-lead-sessions-token",
            )
        self.assertRan(result)
        for r in fake.messages_requests():
            self.assertEqual(r["headers"].get("x-api-key"), "local")
            self.assertNotIn("authorization", r["headers"])

    def test_custom_model_id(self):
        with FakeColibri([text("done")]) as fake:
            result = self.run_script(WORKER, "say done", COLIBRI_BASE_URL=fake.base_url,
                                     COLIBRI_MODEL="qwen3-coder-30b-a3b-colibri")
        self.assertRan(result)
        for r in fake.messages_requests():
            self.assertEqual(r["body"]["model"], "qwen3-coder-30b-a3b-colibri")


class WorkerErrors(Sandbox):
    def test_no_task(self):
        result = self.run_script(WORKER)
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage:", result.stderr)

    def test_colibri_not_running(self):
        result = self.run_script(WORKER, "say done",
                                 COLIBRI_BASE_URL=f"http://127.0.0.1:{free_port()}/v1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not answering", result.stderr)


@needs_claude
class SessionScript(Sandbox):
    def test_uses_bearer_token_and_local_model(self):
        with FakeColibri([text("hello from the fake")]) as fake:
            # Pass-through flags keep the test from loading your own settings.
            result = self.run_script(
                SESSION, "-p", "hi", "--setting-sources", "", "--strict-mcp-config",
                COLIBRI_BASE_URL=fake.base_url,
                ANTHROPIC_API_KEY="the-users-real-key",
            )
        self.assertRan(result)
        self.assertIn("hello from the fake", result.stdout)
        reqs = fake.messages_requests()
        self.assertTrue(reqs)
        for r in reqs:
            self.assertEqual(r["body"]["model"], MODEL_ID)
            self.assertEqual(r["headers"].get("authorization"), "Bearer local")
            self.assertNotIn("x-api-key", r["headers"])


class EnvFile(unittest.TestCase):
    def read_env(self, **env):
        clean = {k: v for k, v in os.environ.items() if not k.startswith(SCRUB)}
        clean.update(env)
        names = ["ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                 "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                 "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_MAX_CONTEXT_TOKENS", "API_TIMEOUT_MS"]
        out = subprocess.run(
            ["bash", "-c", f'. "{ENV_FILE}"; ' + "; ".join(f'echo "{n}=${{{n}}}"' for n in names)],
            env=clean, capture_output=True, text=True, check=True,
        ).stdout
        return dict(line.split("=", 1) for line in out.splitlines())

    def test_defaults(self):
        env = self.read_env()
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8000")
        self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "131072")
        self.assertEqual(env["API_TIMEOUT_MS"], "600000")
        for name in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                     "ANTHROPIC_DEFAULT_HAIKU_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"):
            self.assertEqual(env[name], MODEL_ID, name)

    def test_base_url_forms(self):
        for given in ("http://gpu-box:8000/v1", "http://gpu-box:8000/v1/", "http://gpu-box:8000", "http://gpu-box:8000/"):
            with self.subTest(given=given):
                self.assertEqual(self.read_env(COLIBRI_BASE_URL=given)["ANTHROPIC_BASE_URL"], "http://gpu-box:8000")

    def test_overrides(self):
        env = self.read_env(COLIBRI_MODEL="other", COLIBRI_CONTEXT="65536", API_TIMEOUT_MS="5")
        self.assertEqual(env["ANTHROPIC_MODEL"], "other")
        self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "65536")
        self.assertEqual(env["API_TIMEOUT_MS"], "5")


@needs_claude
class Bootstrap(Sandbox):
    def bootstrap(self, colibri_home):
        return self.run_script(BOOTSTRAP, COLIBRI_HOME=str(colibri_home), BIN_DIR=str(self.tmp / "bin"))

    def test_installs_skill_and_link_without_colibri(self):
        result = self.bootstrap(self.tmp / "no-colibri-here")
        self.assertRan(result)
        skill = self.config / "skills" / "farm" / "SKILL.md"
        self.assertEqual(skill.read_text(), (ROOT / "claude" / "skills" / "farm" / "SKILL.md").read_text())
        link = self.tmp / "bin" / "claude-local-worker"
        self.assertEqual(link.resolve(), WORKER)
        self.assertIn("MCP:     skipped", result.stdout)

    def test_registers_mcp_server_once(self):
        coli = self.tmp / "colibri" / "c" / "coli"
        coli.parent.mkdir(parents=True)
        coli.write_text("")
        first = self.bootstrap(self.tmp / "colibri")
        self.assertRan(first)
        self.assertIn("MCP:     registered colibri", first.stdout)
        self.assertIn(str(coli), (self.config / ".claude.json").read_text())
        second = self.bootstrap(self.tmp / "colibri")
        self.assertRan(second)
        self.assertIn("MCP:     colibri already registered", second.stdout)


if __name__ == "__main__":
    unittest.main()
