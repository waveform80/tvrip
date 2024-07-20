=========
audio_mix
=========

::

    set audio_mix mono|stereo|dpl1|dpl2

This setting specifies the audio mix-down that will be applied to the encoded
audio tracks on the ripped titles. The valid values are:

``mono``
    Mix-down all channels to a single mono channel. ``m`` and ``1`` are aliases
    for this setting.

``stereo``
    Mix-down all channels to two stereo channels. ``s`` and ``2`` are aliases
    for this setting.

``dpl1``
    Mix-down channels to four-channel Dolby Pro Logic (left, right, center, and
    sub).

``dpl2``
    Mix-down channels to 5.1-channel Dolby Pro Logic II (front left and right,
    rear left and right, center, and sub). ``surround``, ``prologic`` and
    ``5.1`` are aliases for this setting. This is the default setting.

.. note::

    Audio pass-through is not currently supported in tvrip.
