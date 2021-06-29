import pytest

from tvrip.ripper import *


def test_scan_whole_disc(db, with_config, with_all_episodes, with_proc):
    disc = Disc(with_config)
    assert repr(disc) == '<Disc()>'
    assert disc.name == 'FOO AND BAR'
    assert disc.serial == '123456789'
    assert disc.ident == '$H1$908e9a2c0bb9299a3c6b2e4a63c8f6b1cc66a9e0'
    assert len(disc.titles) == 10


def test_scan_one_title(db, with_config, with_all_episodes, with_proc):
    disc = Disc(with_config, titles=[1, 2, 3])
    assert disc.name == 'FOO AND BAR'
    assert disc.serial == '123456789'
    assert disc.ident == '$H1$91cd91162ed74120c0971f65a8046cf1ff04509d'
    assert len(disc.titles) == 3
    cmdline = with_proc.run.call_args.args[0]
    assert cmdline[0] == 'HandBrakeCLI'
    assert '--no-dvdnav' not in cmdline


def test_scan_with_dvdread(db, with_config, with_all_episodes, with_proc):
    with_config.dvdnav = False
    disc = Disc(with_config, titles=[1, 2, 3])
    assert disc.name == 'FOO AND BAR'
    assert disc.serial == '123456789'
    assert disc.ident == '$H1$91cd91162ed74120c0971f65a8046cf1ff04509d'
    assert len(disc.titles) == 3
    cmdline = with_proc.run.call_args.args[0]
    assert cmdline[0] == 'HandBrakeCLI'
    assert '--no-dvdnav' in cmdline


def test_scan_wrong_source(db, with_config, with_proc):
    with_config.source = '/dev/badsource'
    with pytest.raises(IOError):
        disc = Disc(with_config)


def test_scan_bad_handbrake(db, with_config, with_proc):
    with_config.source = '/dev/badjson'
    with pytest.raises(IOError):
        disc = Disc(with_config)


def test_play_disc(db, with_config, with_proc):
    disc = Disc(with_config)
    disc.play(with_config)
    cmdline = with_proc.check_call.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert 'dvd:///dev/dvd' in cmdline


def test_play_first_title(db, with_config, with_proc):
    disc = Disc(with_config)
    disc.play(with_config, disc.titles[0])
    cmdline = with_proc.check_call.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert 'dvd:///dev/dvd#1' in cmdline


def test_play_chapters(db, with_config, with_proc):
    disc = Disc(with_config)
    disc.play(with_config, disc.titles[0].chapters[0])
    cmdline = with_proc.check_call.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert 'dvd:///dev/dvd#1:1' in cmdline
