"""Starting and — the hard part — reliably stopping child processes.

An interactive login needs an X server, a VNC server and a browser, all of which outlive
a careless kill: terminating a parent leaves its children running, and a leaked headful
Chromium on a small always-on host grows until the machine is swapping. So every process
here is started in its own process group, killed as a group, and the kill is then
*verified* rather than assumed.
"""

import asyncio
import logging
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# How long a process gets to exit on SIGTERM before the group is killed outright.
TERM_GRACE_SECONDS = 5.0

_PROC = Path("/proc")
# Where an X server puts its socket. Its presence is the only reliable sign that the display
# is ready to be connected to.
_X11_SOCKETS = Path("/tmp/.X11-unix")  # noqa: S108 - the path X11 itself defines


@dataclass
class ManagedProcess:
    """A child process this application is responsible for ending."""

    name: str
    process: asyncio.subprocess.Process
    # A distinctive fragment of the command line, used to prove the process is gone.
    marker: str
    extra_markers: list[str] = field(default_factory=list)

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def running(self) -> bool:
        return self.process.returncode is None


def find_processes(marker: str, *, root: Path = _PROC) -> list[int]:
    """The pids of every process whose command line contains ``marker``.

    Read from ``/proc`` rather than by shelling out to ``pgrep``, so the image needs no extra
    package and the check cannot fail because a tool is missing. On a system without
    ``/proc`` (a developer's macOS machine) nothing is found, which is correct there: the
    processes this looks for only ever run inside the container.
    """
    if not root.is_dir():
        return []
    found: list[int] = []
    encoded = marker.encode()
    for entry in root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            # /proc separates arguments with NUL. Restoring the spaces is what lets a marker
            # be written the way the command reads ("Xvfb :99"); matched against the raw
            # bytes, any marker containing a space would never match anything, and every
            # check that a process is gone would silently succeed.
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ")
        except OSError:
            # The process ended between listing and reading, or is not ours to inspect.
            continue
        if encoded in cmdline:
            found.append(int(entry.name))
    return found


async def start(name: str, argv: list[str], marker: str, **kwargs: object) -> ManagedProcess:
    """Launch ``argv`` in its own process group.

    ``start_new_session`` is what makes the group exist: without it a child shares this
    process's group, and killing that group would take the application down with it.
    """
    logger.info("starting %s: %s", name, " ".join(argv))
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
        **kwargs,
    )
    return ManagedProcess(name=name, process=process, marker=marker)


def _parent_of(pid: int, root: Path) -> int:
    """The pid that started ``pid``, or 0 when that cannot be read."""
    try:
        for line in (root / str(pid) / "status").read_text().splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return 0
    return 0


def protected_pids(root: Path = _PROC) -> set[int]:
    """This process and everything that started it.

    Reaping matches on a fragment of a command line, and a command line is not only the
    process's own: a shell running a script that mentions the marker carries the whole script
    in its argv, and a supervisor's arguments name what it supervises. Killing one of those
    means the application killing its own parent — in a container, PID 1 — which is a much
    worse outcome than failing to clean up a stray.
    """
    chain: set[int] = set()
    pid = os.getpid()
    while pid > 0 and pid not in chain:
        chain.add(pid)
        pid = _parent_of(pid, root)
    return chain


def _signal_group(pid: int, sig: int) -> bool:
    """Signal a whole process group, reporting whether it was still there."""
    try:
        os.killpg(os.getpgid(pid), sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


async def stop(managed: ManagedProcess, *, grace: float = TERM_GRACE_SECONDS) -> None:
    """End a process and everything it started, then check that it worked.

    The group is signalled, not the pid: a browser is a tree of processes, and signalling
    only its root leaves the renderers behind holding their memory.
    """
    if managed.running:
        _signal_group(managed.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(managed.process.wait(), timeout=grace)
        except TimeoutError:
            logger.warning("%s ignored SIGTERM, killing its process group", managed.name)
            _signal_group(managed.pid, signal.SIGKILL)
            await managed.process.wait()

    # "It stopped" is a claim to check, not a fact. A survivor here is the failure mode
    # that grows until the host is thrashing, so it is logged loudly and killed again.
    await reap(managed.marker, *managed.extra_markers)


async def reap(*markers: str, root: Path = _PROC) -> int:
    """Kill any process still matching ``markers``, returning how many were found.

    Called after a stop to catch survivors, and at startup to clear whatever a hard restart
    left behind — a container that was killed rather than shut down leaves an X server and a
    browser holding a profile directory that the next login cannot open.
    """
    killed = 0
    protected = protected_pids(root)
    for marker in markers:
        if not marker:
            continue
        for pid in find_processes(marker, root=root):
            if pid in protected:
                continue
            logger.warning("reaping leftover process %d matching %r", pid, marker)
            if _signal_group(pid, signal.SIGKILL):
                killed += 1
    if killed:
        # Give the kernel a moment to tear the groups down before a caller looks again.
        await asyncio.sleep(0.1)
    return killed


class DisplayNotReady(RuntimeError):
    """The X server did not come up in time."""


async def wait_for_display(
    display: str, timeout: float = 10.0, *, root: Path = _X11_SOCKETS
) -> None:
    """Block until an X server is listening on ``display``.

    Chromium exits immediately if its display is not up yet, reporting only that the browser
    closed — so the wait belongs here, where the real cause can be named, rather than being
    left to surface as an unexplained browser failure.
    """
    socket_path = root / f"X{display.lstrip(':')}"
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if socket_path.exists():
            return
        await asyncio.sleep(0.1)
    raise DisplayNotReady(f"no X server appeared on {display} within {timeout:g}s")
