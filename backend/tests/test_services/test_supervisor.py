"""Starting child processes, and proving they are gone afterwards.

The reason this is tested carefully rather than trusted: a leaked headful browser on a
small always-on host grows until the machine is swapping, and the failure is silent —
everything looks finished.
"""

import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest

from lifeline.services.browser import supervisor


def write_proc_entry(root: Path, pid: int, cmdline: str) -> None:
    """Fake one process in a /proc-shaped directory."""
    entry = root / str(pid)
    entry.mkdir()
    # Real /proc separates arguments with NUL bytes.
    (entry / "cmdline").write_bytes(cmdline.replace(" ", "\0").encode())


class TestFindProcesses:
    def test_finds_a_process_by_a_fragment_of_its_command_line(self, data_dir: Path) -> None:
        write_proc_entry(data_dir, 42, "Xvfb :99 -screen 0 1280x800x24")
        write_proc_entry(data_dir, 43, "sleep 60")

        assert supervisor.find_processes("Xvfb :99", root=data_dir) == [42]

    def test_finds_every_match(self, data_dir: Path) -> None:
        write_proc_entry(data_dir, 1, "chromium --user-data-dir=/data/profiles/3")
        write_proc_entry(data_dir, 2, "chromium --type=renderer --user-data-dir=/data/profiles/3")

        assert sorted(supervisor.find_processes("/data/profiles/3", root=data_dir)) == [1, 2]

    def test_ignores_entries_that_are_not_processes(self, data_dir: Path) -> None:
        (data_dir / "meminfo").write_text("MemTotal: 1")
        write_proc_entry(data_dir, 7, "Xvfb :99")

        assert supervisor.find_processes("Xvfb", root=data_dir) == [7]

    def test_tolerates_a_process_that_ends_mid_scan(self, data_dir: Path) -> None:
        # /proc entries vanish while being read; raising here would abort the whole sweep.
        (data_dir / "99").mkdir()

        assert supervisor.find_processes("anything", root=data_dir) == []

    def test_finds_nothing_where_there_is_no_proc(self, data_dir: Path) -> None:
        assert supervisor.find_processes("Xvfb", root=data_dir / "absent") == []


class TestStartAndStop:
    async def test_starts_a_process_in_its_own_group(self) -> None:
        # Without its own group, killing the group would take this application down with it.
        managed = await supervisor.start("sleeper", ["sleep", "30"], marker="")
        try:
            assert os.getpgid(managed.pid) != os.getpgid(os.getpid())
            assert managed.running is True
        finally:
            await supervisor.stop(managed)

    async def test_stops_a_process(self) -> None:
        managed = await supervisor.start("sleeper", ["sleep", "30"], marker="")

        await supervisor.stop(managed)

        assert managed.running is False

    async def test_kills_a_process_that_ignores_sigterm(self, data_dir: Path) -> None:
        # A browser that will not go quietly still has to go.
        #
        # A shell will not do as the stubborn process: it forwards the signal to its child
        # and then reports the child's status, so it looks as though SIGTERM worked. And the
        # test waits for the handler to be installed, because a signal delivered during
        # interpreter startup is handled by the default disposition and kills it.
        ready = data_dir / "ready"
        managed = await supervisor.start(
            "stubborn",
            [
                sys.executable,
                "-c",
                "import pathlib, signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"pathlib.Path({str(ready)!r}).write_text('1'); time.sleep(30)",
            ],
            marker="",
        )
        try:
            for _ in range(100):
                if ready.exists():
                    break
                await asyncio.sleep(0.05)
            assert ready.exists(), "the stubborn process never installed its handler"

            await supervisor.stop(managed, grace=0.3)
        finally:
            await supervisor.stop(managed)

        assert managed.running is False
        assert managed.process.returncode == -signal.SIGKILL

    async def test_stopping_an_already_dead_process_is_harmless(self) -> None:
        managed = await supervisor.start("brief", ["true"], marker="")
        await managed.process.wait()

        await supervisor.stop(managed)

        assert managed.running is False

    async def test_kills_the_children_too(self) -> None:
        # The point of the process group: a browser is a tree, and signalling only its root
        # leaves the renderers holding their memory.
        script = "sleep 30 & echo $!; wait"
        managed = await asyncio.create_subprocess_exec(
            "sh",
            "-c",
            script,
            stdout=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        child_pid = int((await managed.stdout.readline()).strip())
        wrapped = supervisor.ManagedProcess(name="tree", process=managed, marker="")

        await supervisor.stop(wrapped)

        assert await gone(child_pid)


async def gone(pid: int, *, within_seconds: float = 5.0) -> bool:
    """Whether ``pid`` has left, waiting a little for it to.

    A signal is delivered asynchronously and the process id stays valid while the kernel works
    through it, so asking the instant after the kill answers about timing rather than about
    whether the kill reached the whole tree — which is what made this flake under load.
    """
    deadline = asyncio.get_running_loop().time() + within_seconds
    while asyncio.get_running_loop().time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        await asyncio.sleep(0.05)
    return False


class TestReap:
    async def test_reports_nothing_to_reap(self) -> None:
        assert await supervisor.reap("a-marker-that-matches-nothing-at-all") == 0

    async def test_ignores_an_empty_marker(self) -> None:
        # An empty marker would match every process on the host.
        assert await supervisor.reap("") == 0


class TestWaitForDisplay:
    async def test_returns_once_the_socket_appears(self, data_dir: Path) -> None:
        async def create_socket() -> None:
            await asyncio.sleep(0.05)
            (data_dir / "X99").write_text("")

        task = asyncio.create_task(create_socket())
        try:
            await supervisor.wait_for_display(":99", timeout=2.0, root=data_dir)
        finally:
            await task

    async def test_returns_immediately_when_it_is_already_there(self, data_dir: Path) -> None:
        (data_dir / "X99").write_text("")

        await supervisor.wait_for_display(":99", timeout=0.1, root=data_dir)

    async def test_gives_up_with_a_message_naming_the_display(self, data_dir: Path) -> None:
        # Left to Chromium, the same failure reports only that the browser closed.
        with pytest.raises(supervisor.DisplayNotReady, match=":99"):
            await supervisor.wait_for_display(":99", timeout=0.2, root=data_dir)


class TestReapKills:
    """The kill path, driven through a /proc-shaped directory.

    Pointing the scan at a fake ``/proc`` holding a real pid exercises the same code on any
    platform, including a developer machine that has no ``/proc`` at all.
    """

    async def test_kills_a_process_that_matches_a_marker(self, data_dir: Path) -> None:
        managed = await supervisor.start("leftover", ["sleep", "30"], marker="")
        write_proc_entry(data_dir, managed.pid, "Xvfb :99 -screen 0")
        try:
            killed = await supervisor.reap("Xvfb :99", root=data_dir)

            assert killed == 1
            await asyncio.wait_for(managed.process.wait(), timeout=5)
            assert managed.process.returncode == -signal.SIGKILL
        finally:
            await supervisor.stop(managed)

    async def test_never_kills_this_process(self, data_dir: Path) -> None:
        # The application's own command line can easily contain a marker it is looking for;
        # reaping itself would take the whole service down.
        write_proc_entry(data_dir, os.getpid(), "lifeline /data/profiles")

        assert await supervisor.reap("/data/profiles", root=data_dir) == 0

    async def test_never_kills_a_process_that_started_this_one(self, data_dir: Path) -> None:
        # A shell running a script carries the whole script in its argv, and a supervisor's
        # arguments name what it supervises — so an ancestor's command line very easily contains
        # the marker. Killing one means the application killing its own parent, which in a
        # container is PID 1.
        write_proc_entry(data_dir, os.getpid(), "python -m lifeline")
        (data_dir / str(os.getpid()) / "status").write_text("Name:\tpython\nPPid:\t1\n")
        write_proc_entry(data_dir, 1, "sh -c Xvfb :99 -screen 0 && python -m lifeline")
        (data_dir / "1" / "status").write_text("Name:\tsh\nPPid:\t0\n")

        assert await supervisor.reap("Xvfb :99 ", root=data_dir) == 0

    async def test_reports_this_process_and_its_ancestors(self, data_dir: Path) -> None:
        write_proc_entry(data_dir, os.getpid(), "python")
        (data_dir / str(os.getpid()) / "status").write_text("PPid:\t1\n")
        write_proc_entry(data_dir, 1, "sh")
        (data_dir / "1" / "status").write_text("PPid:\t0\n")

        assert supervisor.protected_pids(root=data_dir) == {os.getpid(), 1}

    async def test_protects_this_process_where_there_is_no_proc(self, data_dir: Path) -> None:
        # A developer machine without /proc: the chain cannot be walked, and the one pid that
        # must never be killed is still known.
        assert supervisor.protected_pids(root=data_dir / "absent") == {os.getpid()}

    async def test_counts_nothing_when_the_process_is_already_gone(
        self, data_dir: Path
    ) -> None:
        managed = await supervisor.start("brief", ["true"], marker="")
        await managed.process.wait()
        write_proc_entry(data_dir, managed.pid, "Xvfb :99")

        assert await supervisor.reap("Xvfb :99", root=data_dir) == 0
