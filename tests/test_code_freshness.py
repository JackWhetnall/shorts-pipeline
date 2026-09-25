"""
core.code_freshness: the app notices when its code changed on disk, stops
taking jobs, and restarts itself once idle.

Regression: a render failed at its last step with "'ChannelConfig' object
has no attribute 'sound'": pipeline code loaded fresh from disk met core
code still in memory from before an update.
"""

from __future__ import annotations

import os
import time

import pytest

from core import code_freshness, jobs


@pytest.fixture
def tree(tmp_path, monkeypatch):
    for folder in code_freshness.WATCHED:
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "a.py").write_text("x = 1\n")
    monkeypatch.setattr(code_freshness, "ROOT", tmp_path)
    monkeypatch.setattr(code_freshness, "_started_with", None)
    return tmp_path


def test_an_edited_file_makes_the_app_stale(tree):
    code_freshness.remember()
    assert not code_freshness.is_stale()
    path = tree / "core" / "a.py"
    path.write_text("x = 2  # changed\n")
    os.utime(path, ns=(time.time_ns(), time.time_ns() + 10_000_000))
    assert code_freshness.is_stale()


def test_a_new_file_makes_it_stale_too(tree):
    code_freshness.remember()
    (tree / "pipeline" / "sound.py").write_text("\n")
    assert code_freshness.is_stale()


def test_never_stale_before_it_has_started(tree):
    assert not code_freshness.is_stale()          # tests and the CLI never remember()


def test_new_jobs_are_refused_while_stale(monkeypatch):
    monkeypatch.setattr(code_freshness, "is_stale", lambda: True)
    with pytest.raises(jobs.JobError) as err:
        jobs.start_job("minute_pastor", {"type": "topic", "topic": "x"})
    assert "restarting" in err.value.user_message


def test_restart_relaunches_the_original_command_then_exits(monkeypatch):
    launched, exited = [], []
    monkeypatch.setattr(code_freshness.subprocess, "Popen",
                        lambda cmd, **kw: launched.append(cmd))
    monkeypatch.setattr(code_freshness.os, "_exit", lambda code: exited.append(code))
    monkeypatch.setattr(code_freshness.sys, "orig_argv", ["pythonw", "tools/start_web.pyw"],
                        raising=False)
    code_freshness.restart()
    assert launched[0][-2:] == ["pythonw", "tools/start_web.pyw"]
    assert "time.sleep" in launched[0][2] and exited == [0]


def test_a_second_copy_of_the_app_refuses_to_start():
    # Regression: a stale logon-task copy and a fresh one both served port
    # 5000; the stale one answered, and every settings page failed.
    import socket
    from web.__main__ import already_running
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    try:
        assert already_running("127.0.0.1", port)
    finally:
        server.close()
    assert not already_running("127.0.0.1", port)
