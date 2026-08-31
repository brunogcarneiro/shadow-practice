# macOS audio setup

1. Install BlackHole 2ch and open Audio MIDI Setup.
2. Create a Multi-Output Device containing your speakers/headphones and BlackHole.
   Select it as macOS output.
3. Create an Aggregate Device whose first two channels are BlackHole and whose third
   channel is your microphone. Rename it `Aggregate Device`, or set
   `SHADOW_PRACTICE_AUDIO_DEVICE` to its exact name.
4. Keep your real microphone selected in the meeting application. Never select the
   aggregate device as the meeting microphone, or remote participants may hear a loop.
5. Grant microphone access to Terminal/Python under System Settings > Privacy & Security.

Use headphones and make a short consented test recording before a real meeting.
