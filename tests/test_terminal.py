import os
from unittest import mock

import pytest

from tvrip.terminal import *


def test_term_size_linux():
    with mock.patch('tvrip.terminal.sys.platform', 'linux'), \
            mock.patch('tvrip.terminal.fcntl') as fnctl:
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
            assert term_size() == (240, 67)
            with mock.patch('os.environ', {}) as environ:
                fnctl.ioctl.side_effect = OSError
                os_open.side_effect = OSError
                environ['COLUMNS'] = 240
                environ['LINES'] = 68
                assert term_size() == (240, 68)
                environ.clear()
                assert term_size() == (80, 24)


def test_term_size_win():
    with mock.patch('tvrip.terminal.sys.platform', 'win32'), \
            mock.patch('tvrip.terminal.ctypes') as ctypes:
        ctypes.windll.kernel32.GetStdHandle.return_value = 1
        ctypes.windll.kernel32.GetConsoleScreenBufferInfo.return_value = (
            b'\x00' * 14 + b'C\x00\xf0\x00' + b'\x00' * 4)
        assert term_size() == (240, 66)


def test_error_handler_ops():
    handler = ErrorHandler()
    assert len(handler) == 3
    assert SystemExit in handler
    assert KeyboardInterrupt in handler
    handler[Exception] = (handler.exc_message, 1)
    assert len(handler) == 4
    assert handler[Exception] == (handler.exc_message, 1)
    del handler[Exception]
    assert len(handler) == 3
    handler.clear()
    assert len(handler) == 0


def test_error_handler_sysexit(capsys):
    handler = ErrorHandler()
    with pytest.raises(SystemExit) as exc:
        handler(SystemExit, SystemExit(4), None)
    assert exc.value.args[0] == 4
    captured = capsys.readouterr()
    assert not captured.out
    assert not captured.err


def test_error_handler_ctrl_c(capsys):
    handler = ErrorHandler()
    with pytest.raises(SystemExit) as exc:
        handler(KeyboardInterrupt, KeyboardInterrupt(3), None)
    assert exc.value.args[0] == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert not captured.err


def test_error_handler_value_error(capsys):
    handler = ErrorHandler()
    handler[Exception] = (handler.exc_message, 1)
    with pytest.raises(SystemExit) as exc:
        handler(ValueError, ValueError('Wrong value'), None)
    assert exc.value.args[0] == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert captured.err == 'Wrong value\n'


def test_error_handler_arg_error(capsys):
    handler = ErrorHandler()
    with pytest.raises(SystemExit) as exc:
        handler(argparse.ArgumentError,
                argparse.ArgumentError(None, 'Invalid option'), None)
    assert exc.value.args[0] == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert captured.err == 'Invalid option\nTry the --help option for more information.\n'


def test_error_handler_traceback(capsys):
    handler = ErrorHandler()
    with mock.patch('traceback.format_exception') as m:
        m.return_value = ['Traceback lines\n', 'from some file\n', 'with some context\n']
        with pytest.raises(SystemExit) as exc:
            handler(ValueError, ValueError('Another wrong value'), {})
        assert exc.value.args[0] == 1
        captured = capsys.readouterr()
        assert not captured.out
        assert captured.err == 'Traceback lines\nfrom some file\nwith some context\n'
