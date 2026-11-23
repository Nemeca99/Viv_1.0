def attempt_one_correction(brain, question, rejected_answer, feedback, temperature):
    prompt = (
        f"{question}\n\n"
        f"Your previous answer was rejected: {rejected_answer}\n"
        f"Tutor feedback: {feedback}\n"
        "Try once more to answer the original question in a complete sentence. "
        "Do not repeat a fragment. If you do not know, say so clearly."
    )
    try:
        result = brain.answer_slot_or_query(prompt, temperature=temperature)
    except Exception as error:
        return {
            "status": "failed",
            "prompt": prompt,
            "error_type": type(error).__name__,
            "error": str(error)[:500],
        }
    return {
        "status": "attempted",
        "prompt": prompt,
        "answer": result.get("answer", ""),
        "gate_state": result.get("gate_state", "UNKNOWN"),
        "s_n": result.get("s_n"),
    }
