"""Tests for the Claude Code scripts, run against tests/fake_colibri.py.

    python3 -m unittest discover -s tests -v

No model, GPU, or network is needed. The tests that start Claude Code need
`claude` on PATH and are skipped without it. Each test gets its own git
repository and its own CLAUDE_CONFIG_DIR, so nothing touches your ~/.claude.
"""

import json
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
START = ROOT / "scripts" / "start-colibri.sh"
INSTALL = ROOT / "scripts" / "install-colibri.sh"
LOG_FORMATTER = ROOT / "scripts" / "claude-local-worker-log.pl"
CODER_ID = "qwen3-coder-30b-a3b-colibri"
WORKER_PROMPT_START = "You are a coding worker running on a local model."
WORKER_TOOLS = {"Read", "Edit", "Write", "Glob", "Grep", "Bash"}

HAVE_CLAUDE = shutil.which("claude") is not None
needs_claude = unittest.skipUnless(HAVE_CLAUDE, "claude is not on PATH")

# Variables from the caller's shell that would change what the scripts do.
SCRUB = ("ANTHROPIC_", "CLAUDE_CODE_", "CLAUDE_LOCAL_WORKER_", "COLIBRI_", "COLI_", "CLAUDECODE", "API_TIMEOUT_MS")


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
        self.logs = self.tmp / "worker-logs"
        self.setup_home = self.tmp / "colibri-setup"
        self.setup_json = self.setup_home / "setup.json"
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
        env["CLAUDE_LOCAL_WORKER_LOGS"] = str(self.logs)
        env["COLI_SETUP_HOME"] = str(self.setup_home)
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

    def test_uses_the_served_model_and_context(self):
        with FakeColibri([text("done")], model_id=CODER_ID, context=65536) as fake:
            result = self.run_script(WORKER, "say done", COLIBRI_BASE_URL=fake.base_url)
        self.assertRan(result)
        reqs = fake.messages_requests()
        self.assertTrue(reqs)
        for r in reqs:
            self.assertEqual(r["body"]["model"], CODER_ID)
        log = (self.logs / "latest.log").read_text()
        self.assertIn(f"model:   {CODER_ID}, 65536 tokens of context", log)

    def test_refuses_a_model_the_server_is_not_serving(self):
        with FakeColibri([text("done")]) as fake:
            result = self.run_script(WORKER, "say done", COLIBRI_BASE_URL=fake.base_url,
                                     COLIBRI_MODEL=CODER_ID)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(f"COLIBRI_MODEL is {CODER_ID}, but Colibri is serving {MODEL_ID}", result.stderr)
        self.assertEqual(fake.messages_requests(), [], "the worker started anyway")

    def test_refuses_a_context_larger_than_the_server_serves(self):
        with FakeColibri([text("done")], context=65536) as fake:
            result = self.run_script(WORKER, "say done", COLIBRI_BASE_URL=fake.base_url,
                                     COLIBRI_CONTEXT="131072")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("COLIBRI_CONTEXT is 131072, but Colibri serves 65536 tokens", result.stderr)
        self.assertEqual(fake.messages_requests(), [], "the worker started anyway")


@needs_claude
class WorkerLog(Sandbox):
    STEPS = [
        tool("Read", file_path="keep.txt"),
        tool("Bash", command="echo one; echo two; false", description="fail on purpose"),
        tool("Edit", file_path="keep.txt", old_string="keep me", new_string="kept"),
        text("all done\nsecond line"),
    ]

    def test_live_log_and_report(self):
        with FakeColibri(self.STEPS) as fake:
            result = self.run_script(WORKER, "edit keep.txt", COLIBRI_BASE_URL=fake.base_url)
        self.assertRan(result)
        # stdout is the final report and nothing else, as before the log existed.
        self.assertEqual(result.stdout, "all done\nsecond line\n")
        self.assertIn(f"worker log: tail -F {self.logs}/latest.log", result.stderr)

        latest = self.logs / "latest.log"
        self.assertTrue(latest.is_symlink())
        run_log = latest.resolve()
        log = run_log.read_text()
        for expected in ["task:    edit keep.txt", f"folder:  {self.repo}",
                         f"model:   {MODEL_ID}, 131072 tokens of context",
                         "Read    keep.txt",
                         "Bash    $ echo one; echo two; false", "! Exit code 1", "! two",
                         "Edit    keep.txt", "- keep me", "+ kept",
                         "says", "all done", "done    finished after 4 turns"]:
            self.assertIn(expected, log)
        # A successful Read or Edit adds no lines of its own.
        self.assertNotIn("updated successfully", log)

        events = [json.loads(line) for line in run_log.with_suffix(".jsonl").read_text().splitlines()]
        self.assertEqual(events[0]["type"], "system")
        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["result"], "all done\nsecond line")

    def test_each_run_gets_its_own_log(self):
        for task in ("first task", "second task"):
            with FakeColibri([text("done")]) as fake:
                self.assertRan(self.run_script(WORKER, task, COLIBRI_BASE_URL=fake.base_url))
        logs = sorted(self.logs.glob("*-*.log"))
        self.assertEqual(len(logs), 2, logs)
        self.assertIn("task:    second task", (self.logs / "latest.log").read_text())


class LogFormatter(unittest.TestCase):
    """The formatter on its own, fed a stream by hand."""

    def format(self, *events):
        log = Path(tempfile.mkdtemp(prefix="local-inference-test-")) / "run.log"
        self.addCleanup(shutil.rmtree, log.parent, ignore_errors=True)
        stream = "".join((e if isinstance(e, str) else json.dumps(e)) + "\n" for e in events)
        result = subprocess.run(["perl", str(LOG_FORMATTER), str(log)], input=stream,
                                capture_output=True, text=True, timeout=30)
        return result, log.read_text() if log.exists() else ""

    def test_stream_without_a_report(self):
        result, log = self.format({"type": "system", "subtype": "init", "model": "m", "cwd": "/x"})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("without a final report", result.stderr)
        self.assertIn("stopped without a final report", log)

    def test_long_output_is_cut_and_bad_lines_are_kept(self):
        output = "\n".join(f"line {n}" for n in range(1, 31))
        result, log = self.format(
            "not json at all",
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "seq 30"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": output}]}},
            {"type": "result", "result": "ok", "is_error": False, "num_turns": 2, "duration_ms": 125000},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "ok\n")
        self.assertIn("?       not json at all", log)
        self.assertIn("line 12", log)
        self.assertNotIn("line 13", log)
        self.assertIn("... 18 more lines", log)
        self.assertIn("finished after 2 turns in 2m05s", log)


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
    NAMES = ["ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
             "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
             "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_MAX_CONTEXT_TOKENS", "API_TIMEOUT_MS"]
    MODEL_SLOTS = NAMES[1:6]

    def source(self, configure, **env):
        """Source the file, run colibri_configure if asked, and print the variables."""
        clean = {k: v for k, v in os.environ.items() if not k.startswith(SCRUB)}
        clean.update(env)
        script = f'. "{ENV_FILE}"; ' + ("colibri_configure || exit $?; " if configure else "")
        script += "; ".join(f'echo "{n}=${{{n}-}}"' for n in self.NAMES)
        return subprocess.run(["bash", "-c", script], env=clean, capture_output=True, text=True)

    def configure(self, model_id=MODEL_ID, context=131072, **env):
        """colibri_configure against a fake serving model_id with context; (exit code, variables, stderr)."""
        with FakeColibri(model_id=model_id, context=context) as fake:
            result = self.source(True, COLIBRI_BASE_URL=fake.base_url, **env)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines())
        return result.returncode, values, result.stderr

    def test_reads_model_and_context_from_the_server(self):
        code, env, err = self.configure(model_id=CODER_ID, context=65536)
        self.assertEqual(code, 0, err)
        for name in self.MODEL_SLOTS:
            self.assertEqual(env[name], CODER_ID, name)
        self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "65536")
        self.assertEqual(env["API_TIMEOUT_MS"], "600000")

    def test_model_override_must_match_the_server(self):
        code, env, err = self.configure(COLIBRI_MODEL=MODEL_ID)
        self.assertEqual(code, 0, err)
        self.assertEqual(env["ANTHROPIC_MODEL"], MODEL_ID)
        code, _, err = self.configure(COLIBRI_MODEL="other")
        self.assertEqual(code, 1)
        self.assertIn(f"COLIBRI_MODEL is other, but Colibri is serving {MODEL_ID}", err)

    def test_context_override_may_be_smaller_never_larger(self):
        code, env, err = self.configure(context=65536, COLIBRI_CONTEXT="32768")
        self.assertEqual(code, 0, err)
        self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "32768")
        code, env, err = self.configure(context=65536, COLIBRI_CONTEXT="65536")
        self.assertEqual(code, 0, err)
        self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "65536")
        code, _, err = self.configure(context=65536, COLIBRI_CONTEXT="65537")
        self.assertEqual(code, 1)
        self.assertIn("COLIBRI_CONTEXT is 65537, but Colibri serves 65536 tokens", err)

    def test_context_override_must_be_a_number(self):
        for bad in ("128k", "0", "-5"):
            with self.subTest(bad=bad):
                code, _, err = self.configure(COLIBRI_CONTEXT=bad)
                self.assertEqual(code, 1)
                self.assertIn("COLIBRI_CONTEXT must be a number of tokens", err)

    def test_server_without_a_context(self):
        code, _, err = self.configure(context=None)
        self.assertEqual(code, 1)
        self.assertIn("did not report its context window", err)
        code, env, err = self.configure(context=None, COLIBRI_CONTEXT="4096")
        self.assertEqual(code, 0, err)
        self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "4096")

    def test_server_not_running(self):
        result = self.source(True, COLIBRI_BASE_URL=f"http://127.0.0.1:{free_port()}/v1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not answering", result.stderr)

    def test_base_url_forms(self):
        for given in ("http://gpu-box:8000/v1", "http://gpu-box:8000/v1/", "http://gpu-box:8000", "http://gpu-box:8000/"):
            with self.subTest(given=given):
                out = self.source(False, COLIBRI_BASE_URL=given).stdout
                self.assertIn("ANTHROPIC_BASE_URL=http://gpu-box:8000\n", out)
        self.assertIn("ANTHROPIC_BASE_URL=http://127.0.0.1:8000\n", self.source(False).stdout)

    def test_timeout_override(self):
        code, env, err = self.configure(API_TIMEOUT_MS="5")
        self.assertEqual(code, 0, err)
        self.assertEqual(env["API_TIMEOUT_MS"], "5")


class StartScript(Sandbox):
    """start-colibri.sh against a fake `coli` that records how it was called."""

    def start(self, **env):
        record = self.tmp / "coli-calls"
        fake = self.tmp / "coli"
        fake.write_text('#!/usr/bin/env bash\n'
                        f'echo "$* COLI_VK_TIER_GB=${{COLI_VK_TIER_GB-unset}}" >> "{record}"\n')
        fake.chmod(0o755)
        result = self.run_script(START, COLI=str(fake), **env)
        calls = record.read_text().splitlines() if record.exists() else []
        return result, calls

    def test_cache_left_to_colibri_by_default(self):
        result, calls = self.start()
        self.assertRan(result)
        self.assertEqual(calls, ["start --background --no-browser COLI_VK_TIER_GB=unset",
                                 "status COLI_VK_TIER_GB=unset"])
        self.assertIn("GPU cache: sized by Colibri", result.stdout)

    def test_saved_cache_is_reported(self):
        # coli start reads the saved setting itself; the script only says which applies.
        self.setup_home.mkdir()
        self.setup_json.write_text(json.dumps({"env": {"COLI_VK_TIER_GB": "2.5"}}))
        result, calls = self.start()
        self.assertRan(result)
        self.assertIn("at most 2.5 GiB of cached model weights on the GPU (saved by install-colibri.sh)", result.stdout)
        self.assertEqual(calls[0], "start --background --no-browser COLI_VK_TIER_GB=unset")

    def test_colibri_variable_is_reported(self):
        result, calls = self.start(COLI_VK_TIER_GB="3")
        self.assertRan(result)
        self.assertIn("at most 3 GiB of cached model weights on the GPU (COLI_VK_TIER_GB)", result.stdout)

    def test_cache_setting_reaches_colibri(self):
        result, calls = self.start(COLIBRI_GPU_CACHE_GB="2.5")
        self.assertRan(result)
        self.assertEqual(calls[0], "start --background --no-browser COLI_VK_TIER_GB=2.5")
        self.assertIn("at most 2.5 GiB", result.stdout)

    def test_cache_setting_must_be_a_number(self):
        for bad in ("2.5GB", "-1", "two", "2."):
            with self.subTest(bad=bad):
                result, calls = self.start(COLIBRI_GPU_CACHE_GB=bad)
                self.assertEqual(result.returncode, 2)
                self.assertIn("must be a number of GiB", result.stderr)
                self.assertEqual(calls, [], "coli ran anyway")

    def test_colibri_not_installed(self):
        result = self.run_script(START, COLI=str(self.tmp / "missing"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("run scripts/install-colibri.sh first", result.stderr)


FAKE_COLI_SETUP = r'''
import json, os, sys
home = os.environ["COLI_SETUP_HOME"]
with open(os.path.join(os.path.dirname(home), "coli-calls"), "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
if sys.argv[1:2] == ["setup"] and "--list" not in sys.argv:
    # Like Colibri: the saved settings are rebuilt on every setup, env included.
    os.makedirs(home, exist_ok=True)
    model = sys.argv[sys.argv.index("--model") + 1]
    with open(os.path.join(home, "setup.json"), "w") as f:
        json.dump({"version": 1, "status": "ready", "model": {"id": model},
                   "env": {"COLI_VULKAN": "1"}, "args": ["web", "--model", model]}, f)
'''


class InstallScript(Sandbox):
    """install-colibri.sh against a fake Colibri checkout whose `coli setup` saves
    settings the way Colibri does, and a fake nvidia-smi."""

    def setUp(self):
        super().setUp()
        missing = [t for t in ("git", "python3", "make", "gcc", "perl") if not shutil.which(t)]
        if missing:
            self.skipTest(f"needs {', '.join(missing)}")
        self.colibri = self.tmp / "colibri"
        (self.colibri / ".git").mkdir(parents=True)
        (self.colibri / "c").mkdir()
        (self.colibri / "c" / "coli").write_text(FAKE_COLI_SETUP)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.gpu_mb("8188")

    def gpu_mb(self, mb):
        tool = self.bin / "nvidia-smi"
        tool.write_text(f"#!/bin/sh\necho {mb}\n")
        tool.chmod(0o755)

    def install(self, *args):
        return self.run_script(INSTALL, *args, COLIBRI_HOME=str(self.colibri), COLIBRI_BACKEND="cpu",
                               COLIBRI_MODEL_DIR=str(self.tmp / "models"),
                               PATH=f"{self.bin}:{os.environ['PATH']}")

    def saved(self):
        return json.loads(self.setup_json.read_text())

    def calls(self):
        path = self.tmp / "coli-calls"
        return path.read_text().splitlines() if path.exists() else []

    def test_default_install(self):
        result = self.install()
        self.assertRan(result)
        self.assertEqual(self.calls(), [f"setup --yes --no-browser --no-start --model qwen36-35b "
                                        f"--dir {self.tmp / 'models'} --backend cpu --ctx 0"])
        self.assertNotIn("COLI_VK_TIER_GB", self.saved()["env"])
        self.assertIn("context automatic, cached weights on the GPU sized by Colibri", result.stdout)

    def test_gpu_cache_is_saved_and_kept_across_installs(self):
        result = self.install("qwen36-35b", "--gpu-cache", "2.5")
        self.assertRan(result)
        saved = self.saved()
        self.assertEqual(saved["env"], {"COLI_VULKAN": "1", "COLI_VK_TIER_GB": "2.5"})
        self.assertEqual(saved["version"], 1, "the rest of Colibri's settings changed")
        self.assertIn("at most 2.5 GiB of cached weights on the GPU", result.stdout)

        # Setup rebuilds the settings; installing again without the flag keeps the cap.
        result = self.install("qwen3-coder-30b")
        self.assertRan(result)
        self.assertEqual(self.saved()["model"]["id"], "qwen3-coder-30b")
        self.assertEqual(self.saved()["env"]["COLI_VK_TIER_GB"], "2.5")

        result = self.install("qwen36-35b", "--gpu-cache=auto")
        self.assertRan(result)
        self.assertNotIn("COLI_VK_TIER_GB", self.saved()["env"])

    def test_model_and_context(self):
        self.assertRan(self.install("qwen3-coder-30b", "--ctx", "65536"))
        self.assertIn("--model qwen3-coder-30b", self.calls()[0])
        self.assertTrue(self.calls()[0].endswith("--ctx 65536"))

    def test_bad_arguments_stop_before_setup(self):
        for args in (["--gpu-cache", "2.5GB"], ["--gpu-cache", "-1"], ["--ctx", "128k"], ["--bogus"], ["--gpu-cache"]):
            with self.subTest(args=args):
                result = self.install(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(self.calls(), [], "setup ran anyway")

    def test_small_gpu_gets_a_suggestion(self):
        result = self.install()
        self.assertIn("This GPU has 8188 MiB", result.stdout)
        self.assertIn("scripts/install-colibri.sh qwen36-35b --gpu-cache 2.5", result.stdout)
        self.assertNotIn("COLI_VK_TIER_GB", self.saved()["env"], "the suggestion was applied")

    def test_no_suggestion_with_a_larger_gpu_or_a_cap(self):
        self.gpu_mb("24576")
        self.assertNotIn("This GPU has", self.install().stdout)
        self.gpu_mb("8188")
        self.assertNotIn("This GPU has", self.install("--gpu-cache", "2.5").stdout)

    def test_settings_in_an_unexpected_shape_stop_the_install(self):
        # A Colibri that saves its settings differently: the cap cannot be kept.
        (self.colibri / "c" / "coli").write_text(FAKE_COLI_SETUP.replace(
            '"env": {"COLI_VULKAN": "1"}, ', ""))
        result = self.install("--gpu-cache", "2.5")
        self.assertEqual(result.returncode, 1)
        self.assertIn('has no "env" object', result.stderr)


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
