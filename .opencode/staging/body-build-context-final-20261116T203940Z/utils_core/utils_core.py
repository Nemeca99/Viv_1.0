class UtilsCore:
    def __init__(self):
        self._health_status = "healthy"
        self._last_health_check = None

    def round_number(self, value, decimals=2):
        """Round a number to the specified number of decimal places."""
        return round(value, decimals)

    def sanitize_string(self, input_str, allowed_chars="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"):
        """Sanitize a string by removing characters not in allowed_chars."""
        return ''.join(char for char in input_str if char in allowed_chars)

    def hash_string(self, input_str, algorithm="sha256"):
        """Hash a string using the specified algorithm."""
        import hashlib
        if algorithm == "sha256":
            return hashlib.sha256(input_str.encode()).hexdigest()
        elif algorithm == "sha1":
            return hashlib.sha1(input_str.encode()).hexdigest()
        elif algorithm == "md5":
            return hashlib.md5(input_str.encode()).hexdigest()
        else:
            raise ValueError(f"Unsupported hashing algorithm: {algorithm}")

    def check_health(self):
        """Check the health status of the module."""
        self._last_health_check = self._health_status
        return self._health_status

    def set_health_status(self, status):
        """Set the health status of the module."""
        self._health_status = status

    def get_last_health_check(self):
        """Get the timestamp of the last health check."""
        return self._last_health_check