# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from unittest import mock

import pytest

from tvrip.main import *


def test_help(capsys):
    with pytest.raises(SystemExit) as err:
        main(['--version'])
    assert err.value.code == 0
    capture = capsys.readouterr()
    assert capture.out.strip() == '2.0'

    with pytest.raises(SystemExit) as err:
        main(['--help'])
    assert err.value.code == 0
    capture = capsys.readouterr()
    assert capture.out.startswith('usage:')


def test_error_exit_no_debug(capsys, monkeypatch):
    with \
        mock.patch('argparse.ArgumentParser.parse_args') as parse_args, \
        monkeypatch.context() as m:

        m.delenv('DEBUG', raising=False)
        parse_args.side_effect = RuntimeError('Oh no! <sound of exploding lemming>')

        assert main([]) == 1
        capture = capsys.readouterr()
        assert 'sound of exploding lemming' in capture.err


def test_error_exit_debug(monkeypatch):
    with \
        mock.patch('argparse.ArgumentParser.parse_args') as parse_args, \
        monkeypatch.context() as m:

        m.setenv('DEBUG', '1')
        parse_args.side_effect = RuntimeError('Oh no! <sound of exploding lemming>')

        with pytest.raises(RuntimeError):
            main([])


def test_error_exit_with_pdb(monkeypatch):
    with \
        mock.patch('argparse.ArgumentParser.parse_args') as parse_args, \
        mock.patch('pdb.post_mortem') as post_mortem, \
        monkeypatch.context() as m:

        m.setenv('DEBUG', '2')
        parse_args.side_effect = RuntimeError('Oh no! <sound of exploding lemming>')

        main([])
        assert post_mortem.called


def test_main_help_cmd(capsys, monkeypatch):
    with \
        mock.patch('cmd.sys.stdin') as stdin, \
        monkeypatch.context() as m:

        m.delenv('DEBUG', raising=False)
        m.setattr(RipCmd, 'use_rawinput', False)
        stdin.readline.side_effect = ['help\n', '']

        assert main([]) == 0
        capture = capsys.readouterr()
        assert 'Command' in capture.out
        assert 'Description' in capture.out
