.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

=====
play
=====

::

    play [title[.chapter]]

The ``play`` command plays the specified title (and optionally chapter) of the
currently scanned disc. Note that a disc must be scanned before this command
can be used. VLC will be started at the specified location and must be quit
before the command prompt will return.

See also :doc:`cmd_scan`, :doc:`cmd_disc`
