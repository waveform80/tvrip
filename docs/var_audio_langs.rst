.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

===========
audio_langs
===========

::

    set audio_langs <lang> [lang]...

This setting lists all the audio languages (as 3-character ISO639 codes) that
you wish to include in rips. For example, if you wish to include English and
Japanese audio tracks::

    (tvrip) set audio_langs eng jpn

See also :doc:`var_audio_all`
