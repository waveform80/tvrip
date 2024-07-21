# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2021-2024 Dave Jones <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import datetime as dt
from pathlib import Path

from tvrip.database import *


def test_config(db, with_config):
    cfg = with_config
    cfg.duration_min = dt.timedelta(minutes=13)
    cfg.duration_max = dt.timedelta(minutes=17)
    assert repr(cfg) == "<Configuration(...)>"
    assert cfg.duration_min == dt.timedelta(minutes=13)
    assert cfg.duration_max == dt.timedelta(minutes=17)


def test_config_langs(db, with_config):
    cfg = with_config
    assert cfg.in_audio_langs('eng')
    assert not cfg.in_audio_langs('der')
    for lang in cfg.audio_langs:
        assert repr(lang) == "<AudioLanguage('eng')>"
    assert cfg.in_subtitle_langs('eng')
    assert not cfg.in_subtitle_langs('der')
    for lang in cfg.subtitle_langs:
        assert repr(lang) == "<SubtitleLanguage('eng')>"


def test_config_paths(db, with_config):
    cfg = with_config
    assert len(cfg.paths) == 3
    assert cfg.get_path('vlc') == Path('vlc')
    assert cfg.get_path('atomicparsley') == Path('AtomicParsley')
    cfg.set_path('handbrake', '/home/me/hb/build/HandBrakeCLI')
    assert cfg.get_path('handbrake') == Path('/home/me/hb/build/HandBrakeCLI')
    for path in cfg.paths:
        if path.name == 'vlc':
            assert repr(path) == "<ConfigPath('vlc', 'vlc')>"


def test_program(db, with_program):
    assert repr(with_program) == "<Program('Foo & Bar')>"


def test_season(db, with_program):
    assert repr(with_program.seasons[0]) == "<Season('Foo & Bar', 1)>"


def test_episode(db, with_program):
    ep = with_program.seasons[0].episodes[0]
    assert repr(ep) == "<Episode('Foo & Bar', 1, 1, 'Foo')>"
    assert not ep.ripped
    ep.disc_id = 'foobarbaz'
    ep.disc_title = 1
    assert ep.ripped
