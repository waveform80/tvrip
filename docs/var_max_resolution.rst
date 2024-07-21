.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

==============
max_resolution
==============

::

    set max_resolution <width>x<height>

Sets the maximum resolution of the output file. Sources with a resolution lower
than this will be unaffected; sources with a higher resolution will be scaled
with their aspect ratio respected. Example::

    (tvrip) set max_resolution 1280x720
