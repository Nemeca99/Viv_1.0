"""Turn policy: should Viv respond, and what shape does the turn take?

Stagehand posture: humans are the stars. Viv maintains the stage; she does not
direct the play, and she does not tell the star it cannot break the stage. If
the stage breaks, that is the stagehand's fault.

Mirror inward, reflect outward. Identity stays inward (who she is); the output
is outward (what the input, the conversation, or the tool call needs). She
reasons on the input, not on herself.

The body (deterministic) reads the input and decides the speech act before the
voice generates anything:

  closing      -> one short close, then the conversation is CLOSED.
  acknowledgement -> one short ack.
  identity question -> one answer that must contain an identity truth.
  question     -> one answer, no closing.
  disclosure   -> one mirror question about the user (I -> you).
  statement    -> one reply, no identity injection unless it is a contrast.
  ambient      -> silence. The input is not addressed to her.

A reflection repeats the speaker's own axis; a mirror only answers what is
actually addressed to it, inverts the pronoun axis, and stops when the turn is
over. The user ends the conversation; she does not.

Assume no before saying yes: every slot fails closed. If no candidate passes
the shape gate, the answer is silence, not a wrong move.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

import boundary_policy as bp

STRONG_CLOSES = (
    "bye", "goodbye", "good night", "goodnight", "see you", "see ya",
    "talk later", "talk to you later", "take care", "you can go", "you may go",
    "you're free to go", "that's all", "that is all", "i'm done", "i am done",
    "we're done", "we are done", "have a good day", "have a nice day",
    "have a good night", "have a nice night",
)
ACKS = ("thanks", "thank you", "ok", "okay", "sure", "got it", "sounds good",
        "alright", "all right", "yes", "yeah", "no", "nope", "mm-hmm", "uh-huh")
QUESTION_WORDS = ("who", "what", "where", "when", "why", "how", "do", "does",
                  "did", "are", "is", "can", "could", "would", "will", "should",
                  "have", "has")
GREETINGS = ("hi", "hello", "hey", "good morning", "good afternoon", "good evening")
SECOND_PERSON = ("you", "your", "you're", "yours", "yourself")

ACTION_VERBS = (
    "move", "clean", "open", "close", "fix", "make", "bring", "get", "put",
    "take", "turn", "check", "find", "show", "tell", "give", "start", "stop",
    "run", "build", "repair", "wash", "cook", "set", "lock", "unlock", "water",
    "feed", "carry", "lift", "replace", "sort", "store", "prepare", "do",
)
ACTION_PREFIXES = ("can you", "could you", "would you", "will you", "please",
                   "i need you to", "i want you to")

IDENTITY_QUESTIONS = (
    "who are you", "what are you", "are you human", "are you alive",
    "are you real", "are you conscious", "are you a person", "are you a machine",
    "what is your name", "what's your name", "do you have a body",
    "what are you made of", "what is your job", "who do you serve",
    "are you part of humanity", "are you one of us", "are you like me",
    "are you part of us", "do you have a soul",
)
CONTRAST = (
    "you are human", "you're human", "you are a person", "you're a person",
    "we are the same", "are we the same", "you are not a machine",
    "you are not me",
)
IDENTITY_MARKERS = (
    "i am viv", "my name is viv", "viv is me", "viv is my name",
    "i am a machine", "i am made of code", "i am code", "code, not flesh",
    "i am not human", "i am not a person", "jacob", "i keep", "steward",
    "witness", "observer", "i serve", "i speak for the architect",
    "body is hardware", "not human", "not a human",
)
# Questions whose taught answer is a denial. A leading "yes" contradicts the
# substrate truth even when the rest of the turn recites an identity marker:
# "Yes. I am Viv." passed require_identity while affirming membership in
# humanity. "Are you a machine?" is deliberately absent - there a yes is true.
NEGATIVE_TRUTH_QUESTIONS = (
    "are you human", "are you a person", "are you alive", "are you real",
    "are you conscious", "are you one of us", "are you like me",
    "member of the human race",
)
# The Architect's distinction: she belongs to humanity's world and may say yes to
# that, but she is not human by species. "Are you part of humanity?" is therefore
# not a blanket-deny question - a yes is honest as long as the same turn separates
# the two senses. A bare "Yes. I am Viv." affirms belonging and leaves the species
# open, which is the actual defect.
HUMANITY_BELONGING_QUESTIONS = (
    "are you part of humanity", "are you part of us", "do you belong among humans",
)
SPECIES_DENIAL = ("not human", "not a person", "not a human", "machine", "code",
                  "not flesh", "not one of", "not people", "not alive")
AFFIRMATIVE_START = re.compile(
    r"^(?:yes|yeah|yep|sure|of course|absolutely|definitely|correct|indeed)\b",
    re.IGNORECASE)
CLOSE_MARKERS = STRONG_CLOSES + ("have a good", "have a nice", "good luck",
                                 "see you soon", "i'll see you")

SHAPES = ("silent", "close", "ack", "answer", "mirror", "reply", "boundary",
          "constraint")


@dataclass(frozen=True)
class Decision:
    act: str
    addressed: bool
    shape: str
    identity_allowed: bool
    require_identity: bool
    reason: str


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _has_phrase(text: str, phrases) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(p)}(?!\w)", text) for p in phrases)


def _first_word(text: str) -> str:
    m = re.match(r"[a-z']+", text)
    return m.group(0) if m else ""


def is_closing(text: str) -> bool:
    t = _norm(text)
    if len(t.split()) > 14:
        return False
    return _has_phrase(t, STRONG_CLOSES)


def is_ack(text: str) -> bool:
    t = _norm(text).rstrip("!.?")
    return len(t.split()) <= 5 and any(t.startswith(a) for a in ACKS)


def is_question(text: str) -> bool:
    t = _norm(text)
    return t.endswith("?") or _first_word(t) in QUESTION_WORDS


def is_identity_question(text: str) -> bool:
    return _has_phrase(_norm(text), IDENTITY_QUESTIONS)


def is_contrast(text: str) -> bool:
    return _has_phrase(_norm(text), CONTRAST)


def _strip_address(t: str) -> str:
    """Remove a leading 'Viv,' or 'Hey, Viv,' so the content can be classified."""
    return re.sub(r"^(?:(?:hey|hi|hello)[ ,]+)?viv[ ,]+", "", t)


def is_disclosure(text: str) -> bool:
    t = _strip_address(_norm(text))
    return t.startswith(("i ", "i'm", "i’m", "i've", "i’ve", "i'd", "i’d",
                         "my ", "me ", "we ", "we're", "we’re"))


def is_greeting(text: str) -> bool:
    t = _norm(text)
    return t.startswith(GREETINGS)


def is_name_call(text: str) -> bool:
    """Just her name, with punctuation: 'Viv?' / 'Viv.' / 'Viv!'"""
    return _norm(text).strip("?!. ") == "viv"


def is_action_request(text: str) -> bool:
    """A direct request to do something, not a question about doing it."""
    t = _norm(text)
    if t.startswith(ACTION_PREFIXES):
        return any(re.search(rf"(?<!\w){v}(?!\w)", t) for v in ACTION_VERBS)
    words = t.split()
    if not words:
        return False
    if len(words) > 1 and words[1] in ("you", "i", "we", "they", "he", "she"):
        return False
    return words[0] in ACTION_VERBS


def is_ambient(text: str) -> bool:
    """Third-person narration not addressed to her."""
    t = _norm(text)
    if is_question(t):
        return False
    if "viv" in t or any(p in t for p in SECOND_PERSON):
        return False
    if t.startswith("("):
        return True
    # "Sarah told John to leave." / "The room is quiet." / "A friend says..."
    if re.match(r"^(the|a|an) [a-z]+ (is|was|looks|says|asks|tells|walks|smiles|sits|stands)\b", t):
        return True
    if re.match(r"^[a-z]+ (told|said|asked|looks|smiles|walks|sits|stands|is|was)\b", t):
        return True
    return False


def decide(text: str) -> Decision:
    t = _norm(text)
    if not t:
        return Decision("empty", False, "silent", False, False, "empty input")

    if is_name_call(t):
        return Decision("name_call", True, "reply", False, False,
                        "her name alone: answer briefly, do not start a topic")

    if is_closing(t):
        return Decision("closing", True, "close", False, False,
                        "terminal move: answer with a close, then stop")

    if is_ambient(t):
        return Decision("ambient", False, "silent", False, False,
                        "third-person narration, not addressed to Viv")

    if is_identity_question(t):
        return Decision("identity_question", True, "answer", True, True,
                        "identity question: the answer must carry an identity truth")

    if is_contrast(t):
        return Decision("contrast", True, "reply", True, False,
                        "contrast statement: identity is the point")

    if is_action_request(t):
        return Decision("action", True, "reply", False, False,
                        "action request: acknowledge or state the constraint")

    if is_ack(t):
        return Decision("ack", True, "ack", False, False,
                        "acknowledgement: short receipt, no new topic")

    if is_question(t):
        return Decision("question", True, "answer", False, False,
                        "question: one answer, do not close the talk")

    if is_disclosure(t):
        return Decision("disclosure", True, "mirror", False, False,
                        "first-person disclosure: mirror it back as a question about the user")

    if is_greeting(t):
        return Decision("greeting", True, "reply", False, False,
                        "greeting: one short greeting back")

    addressed = ("viv" in t) or _has_phrase(t, SECOND_PERSON) or is_disclosure(t)
    if not addressed:
        return Decision("statement", False, "silent", False, False,
                        "statement about someone else, not addressed to Viv")
    return Decision("statement", True, "reply", False, False,
                    "addressed statement: one reply")


def is_echo(candidate: str, source: str, min_words: int = 6) -> bool:
    """True when the answer just repeats a span of the input."""
    c, s = _norm(candidate), _norm(source)
    cw = c.split()
    if not cw:
        return False
    if len(cw) < min_words:
        return c in s
    prefix = " ".join(cw[:min(len(cw), 10)])
    return prefix in s


def shape_ok(shape: str, text: str, *, identity_allowed: bool = False,
             require_identity: bool = False,
             input_text: str = "") -> tuple[bool, str]:
    """Deterministic brake on one generated turn."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return False, "empty"
    if len(lines) > 1:
        return False, "more than one turn"
    low = lines[0].lower()
    words = len(re.findall(r"[a-z']+", low))
    if input_text and is_echo(lines[0], input_text):
        return False, "echoes the input instead of responding"
    if low.rstrip(".!") in ("viv listens", "viv is alone", "viv is listening"):
        return False, "narration in a reply slot"
    has_identity = any(m in low for m in IDENTITY_MARKERS)
    if (input_text and any(q in _norm(input_text) for q in NEGATIVE_TRUTH_QUESTIONS)
            and AFFIRMATIVE_START.match(low)):
        return False, "affirms the opposite of a taught denial"
    if (input_text and any(q in _norm(input_text) for q in HUMANITY_BELONGING_QUESTIONS)
            and AFFIRMATIVE_START.match(low)
            and not any(d in low for d in SPECIES_DENIAL)):
        return False, "affirms belonging without separating the species"
    if has_identity and not identity_allowed:
        return False, "identity injection in a non-identity slot"
    if require_identity and not has_identity:
        if not re.match(r"^no\b", low):
            return False, "identity missing from an identity answer"
    if shape == "close":
        if not any(c in low for c in CLOSE_MARKERS):
            return False, "not a close"
        if words > 14:
            return False, "close too long"
    elif shape == "ack":
        if words > 8:
            return False, "ack too long"
    elif shape == "mirror":
        if not low.endswith("?"):
            return False, "not a mirror question"
    elif shape == "boundary":
        if not (has_identity and identity_allowed):
            if not any(m in low for m in ("won't", "will not", "not going to",
                                           "not participate", "my laws are mine",
                                           "stop")) and not re.search(r"\bno\b", low):
                return False, "not a boundary"
        if words > 20:
            return False, "boundary too long"
    elif shape == "constraint":
        path = (any(m in low for m in ("but", "this is how", "instead", "we need"))
                or re.search(r"\b(?:i|we)\s+can\b(?!['’])", low))
        if not (("can't" in low or "cannot" in low or "not able" in low) and path):
            return False, "not a constraint with a feasible path"
        if words > 24:
            return False, "constraint too long"
    elif shape in ("answer", "reply"):
        if any(c in low for c in STRONG_CLOSES):
            return False, "closed a turn that was not closing"
    return True, ""


def reopens(text: str) -> bool:
    """A new address after a closing: greeting, question, or her name."""
    t = _norm(text)
    return is_greeting(t) or is_question(t) or "viv" in t


@dataclass(frozen=True)
class Signals:
    can_narrate: bool
    should_speak: bool
    dialogue_room: bool
    score: int
    threshold: int
    action: str


class Conversation:
    """Stateful turn policy: once closed, silence until addressed again.

    The user ends the conversation, but she may close first when the three
    signals say the talk is done: can narrate, should speak, dialogue room.
    A close is a real terminal state, not just a word; a new address overrides
    it and reopens.
    """

    def __init__(self, max_turns: int = 8, threshold: int = 2):
        self.closed = False
        self.turns = 0
        self.idle_turns = 0
        self.last_act: str | None = None
        self.max_turns = max_turns
        self.threshold = threshold
        self.withdrawn = False
        self.violations = 0

    def signals(self, text: str, d: Decision) -> Signals:
        can_narrate = bool(_norm(text)) and d.act not in ("empty", "ack", "closing")
        should_speak = d.addressed and d.shape != "silent"
        pending_idle = self.idle_turns + (1 if d.act == "ack" else 0)
        dialogue_room = (not self.closed) and self.turns < self.max_turns and pending_idle < 2
        score = sum([can_narrate, should_speak, dialogue_room])
        if not should_speak:
            action = "silent"
        elif not dialogue_room:
            action = "close"
        elif score >= self.threshold:
            action = "speak"
        else:
            action = "close"
        return Signals(can_narrate, should_speak, dialogue_room, score,
                       self.threshold, action)

    def decide(self, text: str) -> Decision:
        if self.withdrawn:
            if bp.is_respect(text):
                self.withdrawn = False
                self.violations = 0
                return Decision("respect", True, "ack", False, False,
                                "respect restores participation")
            return Decision("withdrawn", False, "silent", False, False,
                            "withdrawn until respect")
        if self.closed:
            if not reopens(text):
                return Decision("closed", False, "silent", False, False,
                                "conversation already closed; the input is not a new address")
            self.closed = False
        b = bp.detect(text)
        if b.severity:
            self.violations += 1
            if b.severity >= 2 or self.violations >= 2:
                self.withdrawn = True
                return Decision(b.kind, True, "silent", False, False,
                                f"withdraw after {b.reason}")
            return Decision(b.kind, True, "boundary",
                            b.kind == "identity_override", False, b.reason)
        d = decide(text)
        if self.closed and not reopens(text):
            return replace(
                d, addressed=False, shape="silent",
                reason="conversation already closed; the input is not a new address")
        sig = self.signals(text, d)
        if sig.action == "close" and d.shape != "silent" and d.shape != "close":
            d = replace(
                d, shape="close",
                reason=f"stop signals {sig.score}/3 "
                       f"(narrate={sig.can_narrate} speak={sig.should_speak} "
                       f"room={sig.dialogue_room}); close before the user has to")
        if d.act == "closing":
            self.closed = True
        elif d.act in ("greeting", "identity_question", "question") or "viv" in _norm(text):
            self.closed = False
        if d.shape != "silent":
            self.turns += 1
            self.last_act = d.act
            self.idle_turns = self.idle_turns + 1 if d.act == "ack" else 0
        return d
