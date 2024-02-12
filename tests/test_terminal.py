import os
from unittest import mock
from ctypes import create_string_buffer

import pytest

from tvrip.terminal import *
from tvrip.terminal.win import term_size as term_size_win
from tvrip.terminal.posix import term_size as term_size_posix


def test_term_size_posix():
    with mock.patch('tvrip.terminal.posix.fcntl') as fnctl:
        fnctl.ioctl.side_effect = [
            OSError,
            b'B\x00\xf0\x00\x00\x00\x00\x00',
        ]
        assert term_size() == (240, 66)
        with mock.patch('os.ctermid') as ctermid, mock.patch('os.open') as os_open:
            fnctl.ioctl.side_effect = [
                OSError,
                OSError,
                OSError,
                b'C\x00\xf0\x00\x00\x00\x00\x00',
            ]
            assert term_size_posix() == (240, 67)
            with mock.patch('os.environ', {}) as environ:
                fnctl.ioctl.side_effect = OSError
                os_open.side_effect = OSError
                environ['COLUMNS'] = 240
                environ['LINES'] = 68
                assert term_size() == (240, 68)
                environ.clear()
                assert term_size() == (80, 24)


def test_term_size_win():
    def GetConsoleScreenBufferInfo(handle, buf):
        if handle == 1:
            buf[:] = b'\x00' * 14 + b'\xef\x00A\x00' + b'\x00' * 4
            return True
        else:
            return False

    with mock.patch('tvrip.terminal.win.ctypes') as ctypes:
        ctypes.create_string_buffer = create_string_buffer
        ctypes.windll.kernel32.GetConsoleScreenBufferInfo.side_effect = GetConsoleScreenBufferInfo
        ctypes.windll.kernel32.GetStdHandle.return_value = 1
        assert term_size_win() == (240, 66)
        ctypes.windll.kernel32.GetStdHandle.return_value = 2
        assert term_size_win() == (80, 25)
        ctypes.windll.kernel32.GetStdHandle.return_value = 0
        assert term_size_win() == (80, 25)
