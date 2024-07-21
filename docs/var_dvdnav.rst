.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

======
dvdnav
======

::

    set dvdnav <bool>

Configures the advanced "Use dvdnav" setting in Handbrake. By default, this is
``on`` and should generally be left that way unless you encounter one of the
rare discs that fails to scan. In this case, falling back to dvdread by
disabling this setting can help.

See also :doc:`cmd_scan`
