# International Morse code + standard timing.
#
# Timing is measured in "units" (a dot = 1 unit):
#   dot                 = 1 unit ON
#   dash                = 3 units ON
#   gap between symbols = 1 unit OFF   (within a letter)
#   gap between letters = 3 units OFF
#   gap between words   = 7 units OFF
#
# "Standard speed" uses the PARIS convention: unit_ms = 1200 / WPM.

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".",
    "F": "..-.", "G": "--.", "H": "....", "I": "..", "J": ".---",
    "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---",
    "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-",
    "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--",
    "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "'": ".----.",
    "!": "-.-.--", "/": "-..-.", "(": "-.--.", ")": "-.--.-",
    "&": ".-...", ":": "---...", ";": "-.-.-.", "=": "-...-",
    "+": ".-.-.", "-": "-....-", "_": "..--.-", '"': ".-..-.",
    "@": ".--.-.",
}


def units_per_wpm(wpm):
    """Milliseconds per Morse unit at the given words-per-minute."""
    wpm = max(1, min(60, int(wpm)))
    return 1200 // wpm


def build_timeline(message, unit_ms):
    """
    Turn a message into a list of (level, end_ms) segments plus the total
    cycle length. `level` is 1 (LED on) or 0 (off); `end_ms` is the cumulative
    end time of that segment. A trailing word gap separates repeats.
    Returns ([], 0) when nothing is renderable.
    """
    events = []  # (level, duration_ms)
    first_letter = True

    for ch in message.upper():
        if ch == " ":
            events.append((0, 7 * unit_ms))
            first_letter = True
            continue

        code = MORSE.get(ch)
        if not code:
            continue

        if not first_letter:
            events.append((0, 3 * unit_ms))  # inter-letter gap
        first_letter = False

        for i, sym in enumerate(code):
            events.append((1, (3 if sym == "-" else 1) * unit_ms))
            if i < len(code) - 1:
                events.append((0, 1 * unit_ms))  # intra-character gap

    if not events:
        return [], 0

    events.append((0, 7 * unit_ms))  # gap before the message repeats

    segments = []
    total = 0
    for level, dur in events:
        if dur <= 0:
            continue
        total += dur
        segments.append((level, total))
    return segments, total
