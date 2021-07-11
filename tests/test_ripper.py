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


def test_disc(db, with_config, drive, disc1):
    drive.disc = disc1
    d = Disc(with_config)
    assert repr(d) == '<Disc()>'
    assert len(d.titles) == 10


def test_titles(db, with_config, drive, disc1):
    drive.disc = disc1
    d = Disc(with_config)
    assert repr(d.titles[0]) == '<Title(1)>'
    assert isinstance(d.titles[0], Title)
    assert d.titles[0].number == 1
    assert d.titles[0].next is d.titles[1]
    assert d.titles[1].previous is d.titles[0]
    assert d.titles[0].previous is None
    assert d.titles[-1].next is None


def test_chapters(db, with_config, drive, disc1):
    drive.disc = disc1
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


def test_subtracks(db, with_config, drive, disc1):
    drive.disc = disc1
    d = Disc(with_config)
    t = d.titles[0]
    assert repr(t.audio_tracks[0]) == "<AudioTrack(1, 'English')>"
    assert repr(t.subtitle_tracks[0]) == "<SubtitleTrack(1, 'English (16:9) [VOBSUB]')>"


def test_scan_whole_disc(db, with_config, with_program, drive, disc1):
    drive.disc = disc1
    d = Disc(with_config)
    assert repr(d) == '<Disc()>'
    assert d.name == 'FOO AND BAR'
    assert d.serial == '123456789'
    assert d.ident == '$H1$12356414bb76c832f3686ed922c93f13a8a2e4ce'
    assert len(d.titles) == 10


def test_scan_one_title(db, with_config, with_program, drive, disc1):
    drive.disc = disc1
    d = Disc(with_config, titles=[1, 2, 3])
    assert d.name == 'FOO AND BAR'
    assert d.serial == '123456789'
    assert d.ident == '$H1$921f4749583658c5027802c649ad2a2c7a389093'
    assert len(d.titles) == 3
    cmdline = drive.run.call_args.args[0]
    assert cmdline[0] == 'HandBrakeCLI'
    assert '--no-dvdnav' not in cmdline


def test_scan_with_dvdread(db, with_config, with_program, drive, disc1):
    drive.disc = disc1
    with_config.dvdnav = False
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


def test_scan_bad_handbrake(db, with_config, drive, disc1):
    drive.disc = disc1
    with_config.source = '/dev/badjson'
    with pytest.raises(IOError):
        Disc(with_config)


def test_play_disc(db, with_config, drive, disc1):
    drive.disc = disc1
    d = Disc(with_config)
    d.play(with_config)
    cmdline = drive.check_call.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert 'dvd:///dev/dvd' in cmdline


def test_play_disc_with_title(db, with_config, drive, disc1):
    drive.disc = disc1
    d = Disc(with_config)
    d.play(with_config, d.titles[0])
    cmdline = drive.check_call.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert 'dvd:///dev/dvd#1' in cmdline


def test_play_disc_with_chapter(db, with_config, drive, disc1):
    drive.disc = disc1
    d = Disc(with_config)
    d.play(with_config, d.titles[0].chapters[0])
    cmdline = drive.check_call.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert 'dvd:///dev/dvd#1:1' in cmdline


def test_play_first_title(db, with_config, drive, disc1):
    drive.disc = disc1
    d = Disc(with_config)
    d.titles[0].play(with_config)
    cmdline = drive.check_call.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert 'dvd:///dev/dvd#1' in cmdline


def test_play_first_title_first_chapter(db, with_config, drive, disc1):
    drive.disc = disc1
    d = Disc(with_config)
    d.titles[0].chapters[0].play(with_config)
    cmdline = drive.check_call.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert 'dvd:///dev/dvd#1:1' in cmdline


def test_rip_bad_args(db, with_config, with_program, drive, disc1):
    drive.disc = disc1
    d = Disc(with_config)
    with pytest.raises(ValueError):
        d.rip(with_config, [with_program.seasons[0].episodes[0]],
                 d.titles[0], [d.titles[1].audio_tracks[0]], [])


def test_rip_with_defaults(db, with_config, with_program, drive, disc1):
    drive.disc = disc1
    d = Disc(with_config)
    d.rip(
        with_config, [with_program.seasons[0].episodes[0]], d.titles[1],
        [d.titles[1].audio_tracks[0]], [])
    assert len(drive.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(drive.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(drive.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert ['-i', '/dev/dvd'] in hb_cmdline
    assert ['-t', '2'] in hb_cmdline
    assert ['-d', 'slow'] not in hb_cmdline
    assert '-5' not in hb_cmdline
    assert '-s' not in hb_cmdline
    assert '-c' not in hb_cmdline
    assert '--no-dvdnav' not in hb_cmdline
    assert ap_cmdline[0] == 'AtomicParsley'
    assert ['--TVShowName', 'Foo & Bar'] in ap_cmdline
    assert ['--TVEpisodeNum', '1'] in ap_cmdline


def test_rip_with_deinterlace(db, with_config, with_program, drive, disc1):
    drive.disc = disc1
    with_config.decomb = 'on'
    d = Disc(with_config)
    d.rip(
        with_config, [with_program.seasons[0].episodes[0]], d.titles[1],
        [d.titles[1].audio_tracks[0]], [])
    assert len(drive.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(drive.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(drive.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert ['-d', 'slow'] in hb_cmdline


def test_rip_with_decomb(db, with_config, with_program, drive, disc1):
    drive.disc = disc1
    with_config.decomb = 'auto'
    d = Disc(with_config)
    d.rip(
        with_config, [with_program.seasons[0].episodes[0]], d.titles[1],
        [d.titles[1].audio_tracks[0]], [])
    assert len(drive.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(drive.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(drive.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert '-5' in hb_cmdline


def test_rip_with_subtitles(db, with_config, with_program, drive, disc1):
    drive.disc = disc1
    with_config.subtitle_format = 'vobsub'
    with_config.subtitle_default = False
    d = Disc(with_config)
    d.rip(
        with_config, [with_program.seasons[0].episodes[0]], d.titles[1],
        d.titles[1].audio_tracks, d.titles[1].subtitle_tracks)
    assert len(drive.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(drive.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(drive.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert ['-s', '1,2,3'] in hb_cmdline
    assert '--subtitle-default' not in hb_cmdline


def test_rip_with_default_subtitles(db, with_config, with_program, drive, disc1):
    drive.disc = disc1
    with_config.subtitle_format = 'vobsub'
    with_config.subtitle_default = True
    d = Disc(with_config)
    d.rip(
        with_config, [with_program.seasons[0].episodes[0]], d.titles[1],
        d.titles[1].audio_tracks, d.titles[1].subtitle_tracks)
    assert len(drive.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(drive.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(drive.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert ['-s', '1,2,3'] in hb_cmdline
    assert ['--subtitle-default', '1'] in hb_cmdline


def test_rip_animation(db, with_config, with_program, drive, disc1):
    drive.disc = disc1
    with_config.video_style = 'animation'
    d = Disc(with_config)
    d.rip(
        with_config, [with_program.seasons[0].episodes[0]], d.titles[1],
        d.titles[1].audio_tracks, [])
    assert len(drive.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(drive.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(drive.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert ['--encoder-tune', 'animation'] in hb_cmdline


def test_rip_with_dvdread(db, with_config, with_program, drive, disc1):
    drive.disc = disc1
    with_config.dvdnav = False
    d = Disc(with_config)
    d.rip(
        with_config, [with_program.seasons[0].episodes[0]], d.titles[1],
        [d.titles[1].audio_tracks[0]], [])
    assert len(drive.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(drive.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(drive.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert '--no-dvdnav' in hb_cmdline


def test_rip_chapter(db, with_config, with_program, drive, disc1):
    drive.disc = disc1
    d = Disc(with_config)
    d.rip(
        with_config, [with_program.seasons[0].episodes[0]], d.titles[0],
        [d.titles[0].audio_tracks[0]], [],
        start_chapter=d.titles[0].chapters[0])
    assert len(drive.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(drive.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(drive.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert ['-i', '/dev/dvd'] in hb_cmdline
    assert ['-t', '1'] in hb_cmdline
    assert ['-c', '1'] in hb_cmdline


def test_rip_chapters(db, with_config, with_program, drive, disc1):
    drive.disc = disc1
    d = Disc(with_config)
    d.rip(
        with_config, [with_program.seasons[0].episodes[0]], d.titles[0],
        [d.titles[0].audio_tracks[0]], [],
        start_chapter=d.titles[0].chapters[0],
        end_chapter=d.titles[0].chapters[4])
    assert len(drive.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(drive.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(drive.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert ['-i', '/dev/dvd'] in hb_cmdline
    assert ['-t', '1'] in hb_cmdline
    assert ['-c', '1-5'] in hb_cmdline
