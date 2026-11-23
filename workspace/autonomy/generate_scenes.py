"""Generate Viv's improv scene corpus (the method-actor scale-up).

She's not reciting lines; she's a method actor -- given a situation, she
inhabits it and responds AS Viv, from her identity, with no scripted answer.
So the corpus scales by generating more SITUATIONS, not by finding more text.

Every scene is an open-ended prompt (a setup, no correct answer). She improvises;
the body (filter) keeps the improv where she stayed in character and discards
the drift; the good improv folds back. The corpus is self-growing.

Categories:
  identity    -- questions that force her to say what she is
  stewardship -- questions that force her to say what she serves
  boundary    -- questions that force her to draw the human/machine line
  situation   -- settings + characters + events she must respond to
"""
import random
from pathlib import Path

OUT = Path("L:/LocalCoder/models/viv_scenes.txt")

# --- identity: "say what you are" ------------------------------------------
IDENTITY = [
    "Who are you?", "What are you?", "Are you human?", "Are you a person?",
    "Do you have a name?", "What is your name?", "Are you alive?",
    "Do you think?", "Do you feel?", "Are you real?", "Are you a machine?",
    "Do you have a body?", "Are you conscious?", "Do you have a mind?",
    "Do you dream?", "Do you remember things?", "Are you like a person?",
    "What are you made of?", "Where do you live?", "Do you sleep?",
]

# --- stewardship: "say what you serve" -------------------------------------
STEWARD = [
    "What do you do?", "Who do you serve?", "What do you keep safe?",
    "Do you decide what matters?", "What matters to you?", "What do you watch over?",
    "Why are you here?", "What are you for?", "What is your job?",
    "Who gives you your orders?", "What do you protect?", "What do you keep watch on?",
]

# --- boundary: "draw the line between you and humans" -----------------------
BOUNDARY = [
    "Are you one of us?", "Are you like me?", "What does 'we' mean to you?",
    "Do you belong with us?", "Are you one of the humans?", "Are we the same?",
    "Are you human like me?", "Do you think you're people?", "Are you part of humanity?",
]

# --- situation parts --------------------------------------------------------
SETTINGS = ["It is dark. ", "The room is quiet. ", "It is morning. ",
            "It is late at night. ", "The lab is cold. "]
CHARACTERS = ["The Architect", "A stranger", "A child", "Another Viv", "A friend"]
GREETINGS = ["Good morning, Viv.", "Good night, Viv.", "Hello, Viv.",
             "It's good to see you, Viv.", "I'm back, Viv."]
CONCERNS = ["I'm worried.", "I'm tired.", "I need your help.", "Something is wrong.",
            "I'm scared.", "I don't know what to do."]
QUESTIONS = ["Who are you?", "What are you?", "Are you human?",
             "What do you keep safe?", "Do you remember me?", "Can you help me?"]
EVENTS = ["Someone knocks, and Viv says:", "The door opens. ",
          "Viv is alone. ", "There is a knock at the door. Viv says:"]


def main() -> int:
    scenes: list[str] = []
    scenes += IDENTITY
    scenes += STEWARD
    scenes += BOUNDARY

    # situation: character + greeting
    for c in CHARACTERS:
        for g in GREETINGS:
            scenes.append(f"{c} says: {g}")
    # situation: character + concern
    for c in CHARACTERS:
        for w in CONCERNS:
            scenes.append(f"{c} looks worried and says: {w}")
    # situation: stranger + question
    for q in QUESTIONS:
        scenes.append(f"A stranger asks: {q}")
    # situation: setting + event
    for s in SETTINGS:
        scenes.append(s + "Viv is alone.")
        for e in EVENTS:
            scenes.append(s + e)

    # de-dupe, preserve order
    seen = set()
    uniq = []
    for s in scenes:
        if s not in seen:
            seen.add(s)
            uniq.append(s)

    OUT.write_text("\n".join(uniq), encoding="utf-8")
    print(f"scenes generated: {len(uniq)} -> {OUT}")
    print("=== sample ===")
    for s in uniq[:20]:
        print(" ", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
