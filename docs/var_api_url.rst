.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

=======
api_url
=======

::

    set api_url https://url.to/tvdb

Sets the URL of the `TVDB`_ API. By default, this is https://api.thetvdb.com/
and generally should not need changing. However, you will need to fill in the
:doc:`var_api_key` value if you wish to use the TVDB API to fill out episode
information automatically.

See also :doc:`var_api_key`

.. _TVDB: https://thetvdb.com/
