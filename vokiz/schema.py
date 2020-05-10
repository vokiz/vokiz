"""Vokiz-specific schema types module."""

import re
import roax.schema as s


class nick(s.str):
    """Schema for user nicknames."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def validate(self, value):
        if not value.isidentifier():
            raise s.SchemaError("Invalid nick format")
        super().validate(value)


class e164(s.str):
    """Schema for E.164 telephone number format."""

    pattern = re.compile(r"^\+[0-9]+$")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def validate(self, value):
        if not e164.pattern.match(value):
            raise s.SchemaError("Invalid E.164 number format")
        super().validate(value)
