.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

=======
config
=======

::

    config

The ``config`` command displays the current configuration of the application.
The :doc:`cmd_set` command can be used to adjust the configuration. See
:doc:`settings` for a full list of configuration variables.

For example:

.. code-block:: text

    (tvrip) config
    ╭──────────────────┬──────────────────────────────────╮
    │ Setting          │ Value                            │
    ├──────────────────┼──────────────────────────────────┤
    │ atomicparsley    │ /usr/bin/AtomicParsley           │
    │ handbrake        │ /usr/local/bin/HandBrakeCLI      │
    │ mkvpropedit      │ /usr/bin/mkvpropedit             │
    │ vlc              │ /usr/bin/vlc                     │
    ├──────────────────┼──────────────────────────────────┤
    │ source           │ /dev/sr1                         │
    │ duration         │ 42-48 (mins)                     │
    │ duplicates       │ all                              │
    ├──────────────────┼──────────────────────────────────┤
    │ target           │ /home/dave/Videos                │
    │ temp             │ /tmp                             │
    │ template         │ {program} - {id} - {name}.{ext}  │
    │ id_template      │ {season}x{episode:02d}           │
    │ output_format    │ mkv                              │
    │ max_resolution   │ 1280x720                         │
    │ decomb           │ off                              │
    │ audio_mix        │ dpl2                             │
    │ audio_all        │ on                               │
    │ audio_langs      │ eng jpn                          │
    │ subtitle_format  │ vobsub                           │
    │ subtitle_all     │ on                               │
    │ subtitle_default │ off                              │
    │ subtitle_langs   │ eng                              │
    │ video_style      │ tv                               │
    │ dvdnav           │ on                               │
    │ api              │ tvdb4                            │
    │ api_key          │                                  │
    ╰──────────────────┴──────────────────────────────────╯

See also :doc:`cmd_set`
