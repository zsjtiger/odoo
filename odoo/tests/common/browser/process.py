# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Lifecycle of the Chrome process: starting it, the reading of its log and the connection to its devtools port."""

from __future__ import annotations

import contextlib
import logging
import os
import pathlib
import subprocess
import time
import typing
import unittest
import psutil
from ..screencast import _preexec
from ..utils import BROWSER_WAIT, CHECK_BROWSER_ITERATIONS, CHECK_BROWSER_SLEEP, HOST, _logger

if typing.TYPE_CHECKING:
    pass


def _spawn_chrome(self, cmd):
    # pylint: disable=subprocess-popen-preexec-fn
    proc = subprocess.Popen(
        cmd,
        stderr=subprocess.DEVNULL,
        preexec_fn=_preexec,
        env={**os.environ, 'TMPDIR': self.user_data_dir},
    )  # noqa: PLW1509

    port_file = pathlib.Path(self.user_data_dir, 'DevToolsActivePort')
    for _ in range(CHECK_BROWSER_ITERATIONS):
        time.sleep(CHECK_BROWSER_SLEEP)
        if port_file.is_file() and port_file.stat().st_size >= 5:
            with port_file.open('r', encoding='utf-8') as f:
                return proc, int(f.readline())

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    self._logger.warning(
        'Chrome headless failed to start:\n%s',
        self.read_log().decode(),
    )
    if port_file.is_file():
        content = port_file.read_text('utf-8')
        _logger.warning('DevToolsActivePort content: %r', content)
    else:
        _logger.warning('DevToolsActivePort not found')
    self.stop()

    raise unittest.SkipTest(f'Failed to detect chrome devtools port after {BROWSER_WAIT :.1f}s.')

@contextlib.contextmanager
def _chrome_start(
        self,
        user_data_dir: str,
        touch_enabled: bool,
        headless=True,
        debug=False,
):
    headless_switches = {
        '--headless': '',
        '--disable-extensions': '',  # Disable all chrome extensions
        '--disable-component-extensions-with-background-pages': '',  # Disable built-in extensions (e.g., PDF viewer, Hangouts...)
        '--disable-background-networking': '',  # Stop background requests (telemetry, updates, safe browsing)
        '--disable-background-timer-throttling': '',  # Prevent Chrome from slowing down JS in inactive tabs
        '--disable-backgrounding-occluded-windows': '',  # Prevent Chrome from suspending hidden windows
        '--disable-renderer-backgrounding': '',  # Keep background rendering processes running at normal priority
        '--disable-breakpad': '',  # Disable the Breakpad crash reporting system
        '--disable-client-side-phishing-detection': '',  # Disable local machine-learning phishing analysis
        '--disable-crash-reporter': '',  # Disable crash report generation
        '--disable-dev-shm-usage': '',  # Use /tmp instead of /dev/shm
        '--disable-namespace-sandbox': '',  # Disable Linux namespace sandboxing
        '--disable-sync': '',  # Completely disable Google account synchronization engine
        '--no-crash-upload': '',  # Prevent uploading crash dumps to Google servers
        '--no-sandbox': '',  # Disable OS-level sandboxing
        '--disable-gpu': '',  # Disable hardware GPU acceleration
        '--enable-unsafe-swiftshader': '',  # Allow software rendering fallback for WebGL when GPU is disabled
        '--mute-audio': '',  # Prevent audio playback from allocating system resources
        '--font-render-hinting': 'none',  # Disable sub-pixel font rendering calculations
        '--disable-gpu-early-init': '',  # Disable proactive early init of GPU process
        '--disable-gpu-sandbox': '',  # Disables the GPU process sandbox
        '--disable-gpu-driver-bug-workarounds': '',  # Disable workarounds for various GPU driver bugs
    }
    switches = {
        # required for tours that use Youtube autoplay conditions (namely website_slides' "course_tour")
        '--autoplay-policy': 'no-user-gesture-required',  # Allow media autoplay without requiring a user click
        '--disable-default-apps': '',  # Disable installation of default apps
        '--disable-domain-reliability': '',  # Stop tracking and sending telemetry for failed network requests
        '--disable-search-engine-choice-screen': '',  # Bypass the EU search engine selection prompt on startup
        '--disable-features': ','.join([
            'Translate',  # Disables Chrome translation
            'MediaRouter',  # Stop scanning for local Cast or media devices
            'InterestFeedContentSuggestions',  # Disables the Discover feed on NTP
        ]),
        '--ash-no-nudges': '',  # Avoids blue bubble "user education" nudges (eg., "… give your browser a new look", Memory Saver)
        '--propagate-iph-for-testing': '',  # Disable all in-product help (IPH) features
        '--no-default-browser-check': '',  # Bypass the prompt asking to make Chrome the default browser
        '--no-first-run': '',  # Skip the welcome screen and first-run setup wizards
        '--proxy-server': '"direct://"',  # Force a direct connection, bypassing any system proxies
        '--proxy-bypass-list': '*',  # Bypass proxy for all domains (eliminates local resolution delays)
        '--remote-debugging-address': HOST,
        '--remote-debugging-port': str(self.remote_debugging_port),
        '--user-data-dir': user_data_dir,
        '--enable-logging': '',
        '--v': str(int(os.environ.get("ODOO_BROWSER_LOG_VERBOSITY", "0"))),
        # FIXME: these next 2 flags are temporarily uncommented to allow client
        # code to manually run garbage collection. This is done as currently
        # the Chrome unit test process doesn't have access to its available
        # memory, so it cannot run the GC efficiently and may run out of memory
        # and crash. These should be re-commented when the process is correctly
        # configured.
        '--enable-precise-memory-info': '',
        '--js-flags': '--expose-gc',
    }
    if headless:
        switches.update(headless_switches)
    if touch_enabled:
        # enable Chrome's Touch mode, useful to detect touch capabilities using
        # "'ontouchstart' in window"
        switches['--touch-events'] = ''
    if debug is not False:
        switches['--auto-open-devtools-for-tabs'] = ''
        switches['--start-fullscreen'] = ''

    cmd = [self.executable]
    cmd += ['%s=%s' % (k, v) if v else k for k, v in switches.items()]
    url = 'about:blank'
    cmd.append(url)
    try:
        proc, devtools_port = self._spawn_chrome(cmd)
    except OSError:
        raise unittest.SkipTest("%s not found" % cmd[0])
    self._logger.info('Chrome pid: %s', proc.pid)
    self._logger.info('Chrome headless temporary user profile dir: %s', self.user_data_dir)
    try:
        yield proc, devtools_port
    finally:
        self._logger.info("Terminating chrome headless with pid %s", proc.pid)
        main = psutil.Process(proc.pid)
        procs = [main] + main.children(recursive=True)
        proc.terminate()
        _, alive = psutil.wait_procs(procs, 5)
        if alive:  # can't early exit, it suppresses the finally'd exception if any
            self._logger.warning(
                "Killing chrome descendants-or-self of %s: %d remaining%s",
                proc.pid,
                len(alive),
                "".join(f"\n- {p.name()} ({p.status()})" for p in alive),
            )
            for p in alive:
                p.kill()
            psutil.wait_procs(alive, 1)
            self.chrome_log_level = logging.RUNBOT

def read_log(self) -> bytes:
    try:
        return pathlib.Path(self.user_data_dir, 'chrome_debug.log').read_bytes()
    except FileNotFoundError:
        return b''
