.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

===
api
===

::

    set api tvdb3|tvdb4

Sets the service used by tvrip to query episode information for new programs or
seasons. By default this is "tvdb4" which is version 4 of the `TVDB`_ API. If
you change this to "tvdb3" you will need to fill in the :doc:`var_api_key`
value.

See also :doc:`var_api_key`, :doc:`cmd_program`, :doc:`cmd_season`

.. _TVDB: https://thetvdb.com/
