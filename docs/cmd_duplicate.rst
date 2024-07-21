.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

=============
duplicate
=============

::

    duplicate <title>[-<title>]

The ``duplicate`` command is used to override the duplicate setting on disc
titles. Usually duplicate titles are automatically detected during
:doc:`cmd_scan` based on identical title lengths. However, some discs have
duplicate titles with different lengths. In this case, it is necessary to
manually specify such duplicates.

If a single title number is given, that title is marked as not being a
duplicate. If a range of title numbers is given, then all titles in that range
will be marked as being duplicates of each other (and titles immediately
adjacent to the range which were formally marked as duplicates will be marked
as not duplicating titles within the range). Examples::

    (tvrip) duplicate 5
    (tvrip) duplicate 1-3

See also :doc:`cmd_scan`
