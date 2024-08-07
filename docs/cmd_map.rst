.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

===
map
===

::

    map [episode title[.start[-end]]]

The ``map`` command is used to define which title on the disc contains the
specified episode. This is used when constructing the filename of ripped
episodes. Note that multiple episodes can be mapped to a single title, to deal
with multi-part episodes being encoded as a single title.

For example::

    (tvrip) map 3 1
    (tvrip) map 7 4
    (tvrip) map 5 2.1-12

If no arguments are specified, the current episode map will be displayed.

See also :doc:`cmd_automap`, :doc:`cmd_unmap`
