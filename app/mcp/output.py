"""MCP object output schemas and validation for OpenAPI response values."""

from copy import deepcopy
import hashlib
import json
from typing import Any

from jsonschema import Draft7Validator, Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import validator_for
from referencing import Registry
from referencing.exceptions import Unresolvable

from app.mcp.errors import ToolExecutionError


def _has_local_refs(value: Any) -> bool:
    if isinstance(value, dict):
        ref = value.get("$ref", value.get("$dynamicRef"))
        return (isinstance(ref, str) and ref.startswith("#")) or any(
            _has_local_refs(item) for item in value.values())
    return isinstance(value, list) and any(_has_local_refs(item) for item in value)


def _preserve_ref_base(schema: dict) -> dict:
    """A moved schema remains its own resource so fragment references stay valid."""
    if "$id" not in schema and _has_local_refs(schema):
        digest = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
        schema["$id"] = f"urn:mcp:output:{digest}"
    return schema


def _json_schema(schema: Any) -> Any:
    """Translate OpenAPI nullable only at schema locations, never in examples."""
    if not isinstance(schema, dict):
        return deepcopy(schema)
    result = deepcopy(schema)
    for keyword in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
        if isinstance(result.get(keyword), dict):
            result[keyword] = {key: _json_schema(value) for key, value in result[keyword].items()}
    for keyword in ("allOf", "anyOf", "oneOf", "prefixItems"):
        if isinstance(result.get(keyword), list):
            result[keyword] = [_json_schema(value) for value in result[keyword]]
    for keyword in ("items", "additionalProperties", "contains", "not", "if", "then", "else",
                    "unevaluatedProperties", "unevaluatedItems", "propertyNames"):
        if keyword in result:
            value = result[keyword]
            result[keyword] = ([_json_schema(item) for item in value] if isinstance(value, list)
                               else _json_schema(value))
    # OpenAPI 3.0 uses boolean exclusive bounds; JSON Schema 2020-12 uses numbers.
    for bound, exclusive in (("minimum", "exclusiveMinimum"), ("maximum", "exclusiveMaximum")):
        if isinstance(result.get(exclusive), bool):
            enabled = result.pop(exclusive)
            if enabled and bound in result:
                result[exclusive] = result.pop(bound)
    nullable = result.pop("nullable", False)
    if nullable:
        union = {"anyOf": [_preserve_ref_base(result), {"type": "null"}]}
        if "$schema" in result:
            union["$schema"] = result["$schema"]
        return union
    return result


def output_contract(schema: dict | None) -> tuple[dict | None, bool]:
    """Normalize on read, including schemas loaded from existing databases."""
    if not schema:
        return None, False
    normalized = _json_schema(schema)
    if normalized.get("type") == "object":
        return normalized, False
    wrapper = {"type": "object", "properties": {"data": _preserve_ref_base(normalized)},
               "required": ["data"]}
    if "$schema" in normalized:
        wrapper["$schema"] = normalized["$schema"]
    return wrapper, True


def structured_output(value: Any, schema: dict | None) -> dict | None:
    contract, wrapped = output_contract(schema)
    result = {"data": value} if wrapped else value
    if contract is not None:
        validation_schema = contract["properties"]["data"] if wrapped else contract
        validator_class = (validator_for(validation_schema, default=None)
                           if "$schema" in validation_schema else Draft202012Validator)
        if validator_class not in (Draft7Validator, Draft202012Validator):
            raise ToolExecutionError("工具输出 schema 使用了不支持的 JSON Schema 版本",
                                     {"type": "unsupported_schema_dialect"})
        try:
            validator_class.check_schema(validation_schema)
            # Explicit empty registry prevents validation from fetching external URLs.
            validator_class(validation_schema, registry=Registry()).validate(value)
        except (ValidationError, SchemaError, Unresolvable) as exc:
            # Validator messages can contain entire values, including credentials.
            raise ToolExecutionError(
                "上游接口返回的数据不符合工具输出 schema，请通过请求 ID 联系管理员排查",
                {"type": "output_validation_error"},
            ) from exc
    return result if isinstance(result, dict) else None
