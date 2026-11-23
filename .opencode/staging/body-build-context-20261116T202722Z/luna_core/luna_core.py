class LunaCore:
    def __init__(self):
        self.status = "healthy"
        self.persona = None
        self.authority_boundary = None
        self.prompt_frame = None

    def set_persona(self, persona):
        self.persona = persona
        self._validate_persona()

    def set_authority_boundary(self, boundary):
        self.authority_boundary = boundary
        self._validate_boundary()

    def set_prompt_frame(self, frame):
        self.prompt_frame = frame
        self._validate_frame()

    def _validate_persona(self):
        if not isinstance(self.persona, dict) or "role" not in self.persona:
            self.status = "persona_invalid"
            raise ValueError("Invalid persona format")

    def _validate_boundary(self):
        if not isinstance(self.authority_boundary, dict) or "limits" not in self.authority_boundary:
            self.status = "boundary_invalid"
            raise ValueError("Invalid authority boundary format")

    def _validate_frame(self):
        if not isinstance(self.prompt_frame, dict) or "structure" not in self.prompt_frame:
            self.status = "frame_invalid"
            raise ValueError("Invalid prompt frame format")

    def get_status(self):
        return self.status

    def get_persona(self):
        return self.persona

    def get_boundary(self):
        return self.authority_boundary

    def get_frame(self):
        return self.prompt_frame

    def enforce_boundary(self, input_text):
        if self.status != "healthy":
            return "System unhealthy"
        if not self.authority_boundary or "limits" not in self.authority_boundary:
            return "Boundary not defined"
        for limit in self.authority_boundary["limits"]:
            if limit["type"] == "keyword" and limit["keyword"] in input_text:
                return f"Boundary violation: {limit['keyword']} detected"
        return "Boundary enforced"

    def frame_prompt(self, input_text):
        if self.status != "healthy":
            return "System unhealthy"
        if not self.prompt_frame or "structure" not in self.prompt_frame:
            return "Frame not defined"
        structured_prompt = self.prompt_frame["structure"].format(input_text=input_text)
        return structured_prompt

    def health_check(self):
        return self.status