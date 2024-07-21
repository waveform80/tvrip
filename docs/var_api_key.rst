.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

=======
api_key
=======

::

    set api_key 1234567890abcdefbeeffacedcafe000

Sets your API key for the `TVDB`_. By default this is blank meaning that all
entry of program, season, and episode information is manual. If this is set to
a valid value, starting a new program or season (with :doc:`cmd_program` or
:doc:`cmd_season`) will query the TVDB for information, and automatically fill
out the necessary entries.

See also :doc:`var_api_key`, :doc:`cmd_program`, :doc:`cmd_season`

.. _TVDB: https://thetvdb.com/
