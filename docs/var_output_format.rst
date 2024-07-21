.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

=============
output_format
=============

::

    set output_format mp4|mkv

Specifies the file format that episodes will be ripped to. This can be set to
either ``mp4``, which is more widely supported, or ``mkv`` which is the more
advanced format (and is the only format suitable for things like PGS subtitle
pass-through on Blu-ray discs). Example::

    (tvrip) set output_format mkv

This setting affects the ``{ext}`` substitution in the :doc:`var_template`.

See also :doc:`var_template`
