"""
One entry per channel. Add new channels here — everything downstream
(quote source, voice, backgrounds, style) is driven by this config.
"""

CHANNELS = {
    "bible_daily": {
        "source": "bible",              # matches a key in quote_source.SOURCES
        "voice": "en-US-GuyNeural",     # edge-tts voice name
        "backgrounds_dir": "backgrounds/bible",
        "style_prompt": (
            "You are writing a short, warm, non-denominational reflection "
            "(3-4 sentences, ~45-60 words) on a Bible verse for a YouTube "
            "Shorts audience. Plain, modern language. No preachiness, "
            "no 'in conclusion', just a grounded human observation about "
            "what the verse means and why it might matter today."
        ),
        "output_dir": "output/bible_daily",
    },
    "shakespeare_lines": {
        "source": "shakespeare",
        "voice": "en-GB-RyanNeural",
        "backgrounds_dir": "backgrounds/shakespeare",
        "style_prompt": (
            "You are writing a short, engaging explainer (3-4 sentences, "
            "~45-60 words) unpacking a Shakespeare quote for a YouTube "
            "Shorts audience with no literary background. Explain what it "
            "means in plain English and why it still lands today. No "
            "academic tone."
        ),
        "output_dir": "output/shakespeare_lines",
    },
}
