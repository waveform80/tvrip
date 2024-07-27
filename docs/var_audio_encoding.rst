.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

==============
audio_encoding
==============

::

    set audio_encoding <encoding>

This setting specifies the encoder used for audio tracks on the ripped titles.
The valid values are:

``av_aac``
    The default AAC encoder included with libav. This generally produces good
    results in most cases at bitrates over 160kbps, but can struggle with
    particular types of noise (wind noise in certain scenes has been known to
    cause issues)

``fdk_aac``
    The Fraunhofer AAC encoder. This generally produces good results at
    bitrates over 160kbps.

    .. warning::

        Most builds of HandBrake do *not* include this codec as it is still
        under patent in many jurisdictions.

``fdk_haac``
    The Fraunhofer HE-AAC encoder. This produces good results in most cases at
    bitrates over 96kbps. Be aware that many players do not support HE-AAC
    decoding.

``mp3``
    The LAME MP3 encoder. This produces good results at bitrates over 192kbps.
    Be aware that some players will not support MP4 sources containing MP3
    audio streams (such players tend to support AAC audio within MP4 only).

``vorbis``
    Xiph's Vorbis encoder. This produces good results at bitrates over
    160kbps. Be aware that, despite being an open format, support for Vorbis
    decoding in players is relatively poor.

``opus``
    Xiph's Opus encoder (the successor to the Vorbis format). This produces
    good results at bitrates over 96kbps. Be aware that, despite being an open
    format, support for Opus decoding in players is relatively poor.

``flac16`` or ``flac24``
    Xiph's FLAC encoder. As a lossless format, this guarantees no degradation
    in audio, but the compression is nowhere near that achieved by the lossy
    codecs (typical bitrate is between 800 and 1400kbps). The number on the
    end determines whether 16-bit or 24-bit samples are used.

    .. note::

        There is almost never a point to using ``flac24`` in ripping DVDs as
        they use 16-bit audio samples. There *may* be a use for ``flac24``
        when ripping Blu-ray, but you'd need to query the source to discover if
        it's actually using more than 16-bit audio samples.

``ac3`` or ``eac3``
    Dolby's AC-3 and E-AC-3 encodings. AC-3 is the native encoding used on DVD
    discs, and produces very good quality, but as a rather old encoding it has
    a rather high bitrate due to poor (by modern standards) compression. It is
    common to find bitrates of 384kbps or greater on DVDs.


.. note::

    Audio pass-through is not currently supported in tvrip.
