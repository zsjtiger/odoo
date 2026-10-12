# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Screencasts of the browser of the tests: the recording of the videos of the tests, or none."""
from __future__ import annotations

import binascii
import datetime
import logging
import os
import pathlib
import platform
import shutil
import subprocess
import time
import typing
from itertools import islice, zip_longest

from odoo.tools.misc import find_in_path

from .utils import get_db_name

if typing.TYPE_CHECKING:
    from .browser import ChromeBrowser


if os.name == 'posix' and platform.system() != 'Darwin':
    # since the introduction of pointer compression in Chrome 80 (v8 v8.0),
    # the memory reservation algorithm requires more than 8GiB of
    # virtual mem for alignment this exceeds our default memory limits.
    def _preexec():
        import resource  # noqa: PLC0415
        resource.setrlimit(resource.RLIMIT_AS, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
else:
    _preexec = None


class NoScreencast:
    def start(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def save(self):
        pass

    def __call__(self, sessionId, data, metadata):
        pass


class Screencaster:
    def __init__(self, browser: ChromeBrowser, directory: str):
        self.stopped = False
        self.browser: ChromeBrowser = browser
        self._logger: logging.Logger = browser._logger
        self.directory = pathlib.Path(directory, get_db_name(), 'screencasts')
        ts = datetime.now()
        self.frames_dir = self.directory / f'frames-{ts:%Y%m%dT%H%M%S.%f}'
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.frames = []

    def start(self):
        self._logger.info('Starting screencast')
        self.browser._websocket_send('Page.startScreencast')

    def __call__(self, sessionId, data, metadata):
        self.browser._websocket_send('Page.screencastFrameAck', params={'sessionId': sessionId})
        if self.stopped:
            # if already stopped, drop the frames as we might have removed the directory already
            return
        outfile = self.frames_dir / f'frame_{len(self.frames):05d}.png'
        try:
            outfile.write_bytes(binascii.a2b_base64(data.encode()))
        except FileNotFoundError:
            return
        self.frames.append({
            'file_path': outfile,
            'timestamp': metadata.get('timestamp')
        })

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.browser._websocket_send('Page.stopScreencast')
        self.stopped = True
        if self.frames_dir.is_dir():
            shutil.rmtree(self.frames_dir, ignore_errors=True)

    def save(self):
        if self.stopped:
            return
        self.browser._websocket_send('Page.stopScreencast')
        # Wait for frames just in case, ideally we'd wait for the Browse.close
        # event or something but that doesn't exist.
        time.sleep(5)
        self.stopped = True
        if not self.frames:
            self._logger.debug('No screencast frames to encode')
            return

        frames, self.frames = self.frames, []
        t = time.time()
        duration = 1/24
        concat_script_path = self.frames_dir.with_suffix('.txt')
        with concat_script_path.open("w") as concat_file:
            for f, next_frame in zip_longest(frames, islice(frames, 1, None)):
                frame_file_path = f['file_path']

                if f['timestamp'] is not None:
                    end_time = next_frame['timestamp'] if next_frame else t
                    duration = end_time - f['timestamp']
                concat_file.write(f"file '{frame_file_path}'\nduration {duration}\n")
            concat_file.write(f"file '{frame_file_path}'")  # needed by the concat plugin

        try:
            ffmpeg_path = find_in_path('ffmpeg')
        except IOError:
            self._logger.runbot('Screencast frames in: %s', self.frames_dir)
            return

        outfile = self.frames_dir.with_suffix('.mp4')
        try:
            subprocess.run([
                ffmpeg_path,
                '-y', '-loglevel', 'warning',
                '-f', 'concat', '-safe', '0', '-i', concat_script_path,
                '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2',
                '-c:v', 'libx265', '-x265-params', 'lossless=1',
                outfile,
            ], preexec_fn=_preexec, check=True)
        except subprocess.CalledProcessError:
            self._logger.error('Failed to encode screencast, screencast frames in %s', self.frames_dir)
        else:
            concat_script_path.unlink()
            shutil.rmtree(self.frames_dir, ignore_errors=True)
            self._logger.runbot('Screencast in: %s', outfile)
