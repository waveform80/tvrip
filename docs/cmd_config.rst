=======
config
=======

::

    config


Description
===========

The ``config`` command displays the current configuration of the application.
The :doc:`cmd_set` command can be used to adjust the configuration. See
:doc:`variables` for a full list of configuration variables.


Example
=======

.. code-block:: text

    (tvrip) config

    External Utility Paths:

    atomicparsley    = /usr/bin/AtomicParsley
    handbrake        = /usr/local/bin/HandBrakeCLI
    vlc              = /usr/bin/vlc

    Scanning Configuration:

    source           = /dev/sr1
    duration         = 42.0-48.0 (mins)
    duplicates       = all

    Ripping Configuration:

    target           = /home/dave/Videos
    temp             = /tmp
    template         = {program} - {id} - {name}.{ext}
    id_template      = {season}x{episode:02d}
    output_format    = mkv
    max_resolution   = 1280x720
    decomb           = auto
    audio_mix        = dpl2
    audio_all        = on
    audio_langs      = eng jpn
    subtitle_format  = vobsub
    subtitle_all     = on
    subtitle_default = off
    subtitle_langs   = eng
    video_style      = tv
    dvdnav           = yes
    api_url          = https://api.thetvdb.com/
    api_key          =


See Also
========

:doc:`cmd_set`
