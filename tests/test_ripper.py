# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2021-2024 Dave Jones <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import time

import pytest

from tvrip.ripper import *


class Cmdline(list):
    def __contains__(self, item):
        if isinstance(item, list):
            l = len(item)
            for i in range(len(self) - l + 1):
                if item == self[i:i + l]:
                    return True
            return False
        else:
            return super().__contains__(item)


def test_disc(db, with_config, drive, foo_disc1):
    drive.disc = foo_disc1
    d = Disc(with_config)
    assert repr(d) == '<Disc()>'
    assert len(d.titles) == 11


def test_titles(db, with_config, drive, foo_disc1):
    drive.disc = foo_disc1
    d = Disc(with_config)
    assert repr(d.titles[0]) == '<Title(1)>'
    assert isinstance(d.titles[0], Title)
    assert d.titles[0].number == 1
    assert d.titles[0].next is d.titles[1]
    assert d.titles[1].previous is d.titles[0]
    assert d.titles[0].previous is None
    assert d.titles[-1].next is None


def test_chapters(db, with_config, drive, foo_disc1):
    drive.disc = foo_disc1
    d = Disc(with_config)
    agg_title = d.titles[0]
    src_titles = [t for t in d.titles if t.number in (2, 3, 5, 6, 8)]
    assert len(agg_title.chapters) == sum(
        1 for t in src_titles for c in t.chapters)
    for c1, c2 in zip(agg_title.chapters, [c for t in src_titles for c in t.chapters]):
        assert c1.duration == c2.duration
    t = d.titles[0]
    assert isinstance(t.chapters[0], Chapter)
    assert repr(t.chapters[0]) == '<Chapter(1, 0:07:08.571429)>'
    assert t.chapters[0].start == time(0, 0, 0)
    assert t.chapters[1].start == time(0, 7, 8, 571429)
    assert t.chapters[0].finish == t.chapters[1].start
    assert t.chapters[0].next is t.chapters[1]
    assert t.chapters[0].previous is None
    assert t.chapters[1].previous is t.chapters[0]
    assert t.chapters[-1].next is None


def test_subtracks(db, with_config, drive, foo_disc1):
    drive.disc = foo_disc1
    d = Disc(with_config)
    t = d.titles[0]
    assert repr(t.audio_tracks[0]) == "<AudioTrack(1, 'English')>"
    assert repr(t.subtitle_tracks[0]) == "<SubtitleTrack(1, 'English (16:9) [VOBSUB]')>"


def test_scan_whole_disc(db, with_config, with_program, drive, foo_disc1):
    drive.disc = foo_disc1
    d = Disc(with_config)
    assert repr(d) == '<Disc()>'
    assert d.name == 'FOO AND BAR'
    assert d.serial == '123456789'
    assert d.ident == '$H1$95b276dd0eed858ce07b113fb0d48521ac1a7caf'
    assert len(d.titles) == 11


def test_scan_one_title(db, with_config, with_program, drive, foo_disc1):
    drive.disc = foo_disc1
    d = Disc(with_config, titles=[1, 2, 3])
    assert d.name == 'FOO AND BAR'
    assert d.serial == '123456789'
    assert d.ident == '$H1$921f4749583658c5027802c649ad2a2c7a389093'
    assert len(d.titles) == 3
    cmdline = drive.run.call_args.args[0]
    assert cmdline[0] == 'HandBrakeCLI'
    assert '--no-dvdnav' not in cmdline


def test_scan_with_dvdread(db, with_config, with_program, drive, foo_disc1):
    drive.disc = foo_disc1
    with_config = with_config._replace(dvdnav=False)
    d = Disc(with_config, titles=[1, 2, 3])
    assert d.name == 'FOO AND BAR'
    assert d.serial == '123456789'
    assert d.ident == '$H1$921f4749583658c5027802c649ad2a2c7a389093'
    assert len(d.titles) == 3
    cmdline = drive.run.call_args.args[0]
    assert cmdline[0] == 'HandBrakeCLI'
    assert '--no-dvdnav' in cmdline


def test_scan_wrong_source(db, with_config, drive):
    drive.disc = None
    with pytest.raises(IOError):
        Disc(with_config)


def test_scan_bad_handbrake(db, with_config, drive, foo_disc1):
    drive.disc = foo_disc1
    with_config = with_config._replace(source='/dev/badjson')
    with pytest.raises(IOError):
        Disc(with_config)


def test_play_disc(db, with_config, drive, foo_disc1):
    drive.disc = foo_disc1
    d = Disc(with_config)
    d.play(with_config)
    cmdline = drive.run.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert f'dvd://{with_config.source}' in cmdline


def test_play_disc_with_title(db, with_config, drive, foo_disc1):
    drive.disc = foo_disc1
    d = Disc(with_config)
    d.play(with_config, d.titles[0])
    cmdline = drive.run.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert f'dvd://{with_config.source}#1' in cmdline


def test_play_disc_with_chapter(db, with_config, drive, foo_disc1):
    drive.disc = foo_disc1
    d = Disc(with_config)
    d.play(with_config, d.titles[0].chapters[0])
    cmdline = drive.run.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert f'dvd://{with_config.source}#1:1' in cmdline


def test_play_first_title(db, with_config, drive, foo_disc1):
    drive.disc = foo_disc1
    d = Disc(with_config)
    d.titles[0].play(with_config)
    cmdline = drive.run.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert f'dvd://{with_config.source}#1' in cmdline


def test_play_first_title_first_chapter(db, with_config, drive, foo_disc1):
    drive.disc = foo_disc1
    d = Disc(with_config)
    d.titles[0].chapters[0].play(with_config)
    cmdline = drive.run.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert f'dvd://{with_config.source}#1:1' in cmdline


def test_rip_bad_args(db, with_config, with_program, drive, foo_disc1):
    drive.disc = foo_disc1
    d = Disc(with_config)
    episodes = db.get_episodes()
    with pytest.raises(ValueError):
        d.rip(
            with_config, [episodes[0]], d.titles[0],
            [d.titles[1].audio_tracks[0]], [])


def test_rip_with_defaults(db, with_program, drive, foo_disc1):
    episodes = db.get_episodes()
    drive.disc = foo_disc1
    d = Disc(with_program)
    d.rip(
        with_program, [episodes[0]], d.titles[1],
        [d.titles[1].audio_tracks[0]], [])
    assert len(drive.run.call_args_list) == 4
    test_cmdline = Cmdline(drive.run.call_args_list[0].args[0])
    scan_cmdline = Cmdline(drive.run.call_args_list[1].args[0])
    rip_cmdline = Cmdline(drive.run.call_args_list[2].args[0])
    ap_cmdline = Cmdline(drive.run.call_args_list[3].args[0])
    assert test_cmdline[0] == 'HandBrakeCLI'
    assert ['-h'] in test_cmdline
    assert rip_cmdline[0] == 'HandBrakeCLI'
    assert ['-i', str(with_program.source)] in rip_cmdline
    assert ['-t', '2'] in rip_cmdline
    assert ['-d', 'slow'] not in rip_cmdline
    assert '-5' in rip_cmdline
    assert '-s' not in rip_cmdline
    assert '-c' not in rip_cmdline
    assert '--no-dvdnav' not in rip_cmdline
    assert ap_cmdline[0] == 'AtomicParsley'
    assert ['--TVShowName', 'Foo & Bar'] in ap_cmdline
    assert ['--TVEpisodeNum', '1'] in ap_cmdline


def test_rip_with_deinterlace(db, with_program, drive, foo_disc1):
    with_program = with_program._replace(decomb='on')
    episodes = db.get_episodes()
    drive.disc = foo_disc1
    d = Disc(with_program)
    d.rip(
        with_program, [episodes[0]], d.titles[1],
        [d.titles[1].audio_tracks[0]], [])
    assert len(drive.run.call_args_list) == 4
    test_cmdline = Cmdline(drive.run.call_args_list[0].args[0])
    scan_cmdline = Cmdline(drive.run.call_args_list[1].args[0])
    rip_cmdline = Cmdline(drive.run.call_args_list[2].args[0])
    ap_cmdline = Cmdline(drive.run.call_args_list[3].args[0])
    assert test_cmdline[0] == 'HandBrakeCLI'
    assert ['-h'] in test_cmdline
    assert rip_cmdline[0] == 'HandBrakeCLI'
    assert ['-d', 'slow'] in rip_cmdline


def test_rip_without_decomb(db, with_program, drive, foo_disc1):
    with_program = with_program._replace(decomb='off')
    episodes = db.get_episodes()
    drive.disc = foo_disc1
    d = Disc(with_program)
    d.rip(
        with_program, [episodes[0]], d.titles[1],
        [d.titles[1].audio_tracks[0]], [])
    assert len(drive.run.call_args_list) == 4
    test_cmdline = Cmdline(drive.run.call_args_list[0].args[0])
    scan_cmdline = Cmdline(drive.run.call_args_list[1].args[0])
    rip_cmdline = Cmdline(drive.run.call_args_list[2].args[0])
    ap_cmdline = Cmdline(drive.run.call_args_list[3].args[0])
    assert test_cmdline[0] == 'HandBrakeCLI'
    assert ['-h'] in test_cmdline
    assert rip_cmdline[0] == 'HandBrakeCLI'
    assert '-5' not in rip_cmdline


def test_rip_with_subtitles(db, with_program, drive, foo_disc1):
    with_program = with_program._replace(
        subtitle_format='vobsub', subtitle_default=False)
    episodes = db.get_episodes()
    drive.disc = foo_disc1
    d = Disc(with_program)
    d.rip(
        with_program, [episodes[0]], d.titles[1],
        d.titles[1].audio_tracks, d.titles[1].subtitle_tracks)
    assert len(drive.run.call_args_list) == 4
    test_cmdline = Cmdline(drive.run.call_args_list[0].args[0])
    scan_cmdline = Cmdline(drive.run.call_args_list[1].args[0])
    rip_cmdline = Cmdline(drive.run.call_args_list[2].args[0])
    ap_cmdline = Cmdline(drive.run.call_args_list[3].args[0])
    assert test_cmdline[0] == 'HandBrakeCLI'
    assert ['-h'] in test_cmdline
    assert rip_cmdline[0] == 'HandBrakeCLI'
    assert ['-s', '1,2,3'] in rip_cmdline
    assert '--subtitle-default' not in rip_cmdline


def test_rip_with_default_subtitles(db, with_program, drive, foo_disc1):
    with_program = with_program._replace(
        subtitle_format='vobsub', subtitle_default=True)
    episodes = db.get_episodes()
    drive.disc = foo_disc1
    d = Disc(with_program)
    d.rip(
        with_program, [episodes[0]], d.titles[1],
        d.titles[1].audio_tracks, d.titles[1].subtitle_tracks)
    assert len(drive.run.call_args_list) == 4
    test_cmdline = Cmdline(drive.run.call_args_list[0].args[0])
    scan_cmdline = Cmdline(drive.run.call_args_list[1].args[0])
    rip_cmdline = Cmdline(drive.run.call_args_list[2].args[0])
    ap_cmdline = Cmdline(drive.run.call_args_list[3].args[0])
    assert test_cmdline[0] == 'HandBrakeCLI'
    assert ['-h'] in test_cmdline
    assert rip_cmdline[0] == 'HandBrakeCLI'
    assert ['-s', '1,2,3'] in rip_cmdline
    assert ['--subtitle-default', '1'] in rip_cmdline


def test_rip_animation(db, with_program, drive, foo_disc1):
    with_program = with_program._replace(video_style='animation')
    episodes = db.get_episodes()
    drive.disc = foo_disc1
    d = Disc(with_program)
    d.rip(
        with_program, [episodes[0]], d.titles[1],
        d.titles[1].audio_tracks, [])
    assert len(drive.run.call_args_list) == 4
    test_cmdline = Cmdline(drive.run.call_args_list[0].args[0])
    scan_cmdline = Cmdline(drive.run.call_args_list[1].args[0])
    rip_cmdline = Cmdline(drive.run.call_args_list[2].args[0])
    ap_cmdline = Cmdline(drive.run.call_args_list[3].args[0])
    assert test_cmdline[0] == 'HandBrakeCLI'
    assert ['-h'] in test_cmdline
    assert rip_cmdline[0] == 'HandBrakeCLI'
    assert ['--encoder-tune', 'animation'] in rip_cmdline


def test_rip_with_dvdread(db, with_program, drive, foo_disc1):
    with_program = with_program._replace(dvdnav=False)
    episodes = db.get_episodes()
    drive.disc = foo_disc1
    d = Disc(with_program)
    d.rip(
        with_program, [episodes[0]], d.titles[1],
        [d.titles[1].audio_tracks[0]], [])
    assert len(drive.run.call_args_list) == 4
    test_cmdline = Cmdline(drive.run.call_args_list[0].args[0])
    scan_cmdline = Cmdline(drive.run.call_args_list[1].args[0])
    rip_cmdline = Cmdline(drive.run.call_args_list[2].args[0])
    ap_cmdline = Cmdline(drive.run.call_args_list[3].args[0])
    assert test_cmdline[0] == 'HandBrakeCLI'
    assert ['-h'] in test_cmdline
    assert rip_cmdline[0] == 'HandBrakeCLI'
    assert '--no-dvdnav' in rip_cmdline


def test_rip_chapter(db, with_program, drive, foo_disc1):
    episodes = db.get_episodes()
    drive.disc = foo_disc1
    d = Disc(with_program)
    d.rip(
        with_program, [episodes[0]], d.titles[0],
        [d.titles[0].audio_tracks[0]], [],
        start_chapter=d.titles[0].chapters[0])
    assert len(drive.run.call_args_list) == 4
    test_cmdline = Cmdline(drive.run.call_args_list[0].args[0])
    scan_cmdline = Cmdline(drive.run.call_args_list[1].args[0])
    rip_cmdline = Cmdline(drive.run.call_args_list[2].args[0])
    ap_cmdline = Cmdline(drive.run.call_args_list[3].args[0])
    assert test_cmdline[0] == 'HandBrakeCLI'
    assert ['-h'] in test_cmdline
    assert rip_cmdline[0] == 'HandBrakeCLI'
    assert ['-i', str(with_program.source)] in rip_cmdline
    assert ['-t', '1'] in rip_cmdline
    assert ['-c', '1'] in rip_cmdline


def test_rip_chapters(db, with_program, drive, foo_disc1):
    episodes = db.get_episodes()
    drive.disc = foo_disc1
    d = Disc(with_program)
    d.rip(
        with_program, [episodes[0]], d.titles[0],
        [d.titles[0].audio_tracks[0]], [],
        start_chapter=d.titles[0].chapters[0],
        end_chapter=d.titles[0].chapters[4])
    assert len(drive.run.call_args_list) == 4
    test_cmdline = Cmdline(drive.run.call_args_list[0].args[0])
    scan_cmdline = Cmdline(drive.run.call_args_list[1].args[0])
    rip_cmdline = Cmdline(drive.run.call_args_list[2].args[0])
    ap_cmdline = Cmdline(drive.run.call_args_list[3].args[0])
    assert test_cmdline[0] == 'HandBrakeCLI'
    assert ['-h'] in test_cmdline
    assert rip_cmdline[0] == 'HandBrakeCLI'
    assert ['-i', str(with_program.source)] in rip_cmdline
    assert ['-t', '1'] in rip_cmdline
    assert ['-c', '1-5'] in rip_cmdline
