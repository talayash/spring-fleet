"""Validate the JSON Schema keywords used by this project's schemas (stdlib).

This is intentionally not a general JSON Schema implementation.
"""


def validate(value, schema, path="$"):
    errors = []
    checks = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "null": lambda v: v is None,
    }
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    if types and not any(checks[t](value) for t in types):
        return ["{}: expected {}".format(path, " or ".join(types))]
    if "enum" in schema and value not in schema["enum"]:
        errors.append("{}: must be one of {}".format(path, schema["enum"]))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append("{}.{}: required".format(path, key))
        for key, item in value.items():
            if key in properties:
                errors.extend(validate(item, properties[key], path + "." + key))
            elif schema.get("additionalProperties") is False:
                errors.append("{}.{}: unknown property".format(path, key))
    if isinstance(value, list):
        for limit, comparison in (("minItems", len(value) < schema.get("minItems", 0)),
                                  ("maxItems", len(value) > schema.get("maxItems", len(value)))):
            if comparison:
                errors.append("{}: violates {} {}".format(path, limit, schema[limit]))
        for index, item in enumerate(value):
            errors.extend(validate(item, schema.get("items", {}), "{}[{}]".format(path, index)))
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        errors.append("{}: must not be empty".format(path))
    if isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            errors.append("{}: out of range".format(path))
    return errors
