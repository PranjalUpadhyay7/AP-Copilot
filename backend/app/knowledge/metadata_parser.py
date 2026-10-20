"""Parses ArduPilot parameter metadata."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from app.knowledge.rag_store import param_doc_url
from app.models.params import ParamDefinition


def _parse_one(name: str, info: dict[str, Any], vehicle_types: list[str], firmware_version: str) -> ParamDefinition:
    range_info = info.get("Range")
    min_value = float(range_info["low"]) if range_info and "low" in range_info else None
    max_value = float(range_info["high"]) if range_info and "high" in range_info else None

    increment = float(info["Increment"]) if "Increment" in info else None

    bitmask_raw = info.get("Bitmask")
    bitmask = {int(k): v for k, v in bitmask_raw.items()} if bitmask_raw else None

    values = info.get("Values") or None

    reboot_required = str(info.get("RebootRequired", "")).strip().lower() == "true"

    return ParamDefinition(
        name=name,
        vehicle_types=vehicle_types,
        firmware_version=firmware_version,
        description=info.get("Description", ""),
        unit=info.get("Units") or None,
        min_value=min_value,
        max_value=max_value,
        increment=increment,
        bitmask=bitmask,
        reboot_required=reboot_required,
        values=values,
        doc_url=param_doc_url(name, vehicle_types),
    )


def parse_param_definitions(
    raw_json: dict[str, Any],
    *,
    vehicle_types: list[str],
    firmware_version: str,
) -> dict[str, ParamDefinition]:
    """Flattens param_parse.py's `--format json` group-keyed output."""
    definitions: dict[str, ParamDefinition] = {}
    for group_value in raw_json.values():
        if not isinstance(group_value, dict):
            continue
        for param_name, param_info in group_value.items():
            if not isinstance(param_info, dict):
                continue
            definitions[param_name] = _parse_one(param_name, param_info, vehicle_types, firmware_version)
    return definitions


def parse_param_definitions_file(
    path: str | Path,
    *,
    vehicle_types: list[str],
    firmware_version: str,
) -> dict[str, ParamDefinition]:
    raw_json = json.loads(Path(path).read_text())
    return parse_param_definitions(raw_json, vehicle_types=vehicle_types, firmware_version=firmware_version)


def extract_param_suffixes(raw_json: dict[str, Any]) -> dict[str, str]:
    suffixes: dict[str, str] = {}
    for group_key, group_value in raw_json.items():
        if group_key == "json" or not isinstance(group_value, dict):
            continue
        for param_name in group_value:
            suffixes[param_name] = param_name.removeprefix(group_key)
    return suffixes


_PDEF_COMMIT_RE = re.compile(r"Generated from git tag \S+ \(([0-9a-f]{40})\)")


def pdef_xml_commit(xml_text: str) -> str | None:
    """The full commit SHA an official apm.pdef.xml says it was generated from."""
    m = _PDEF_COMMIT_RE.search(xml_text[:2000])
    return m.group(1) if m else None


def parse_pdef_xml(xml_text: str, *, vehicle_type: str, firmware_version: str) -> dict[str, ParamDefinition]:
    """Parse ArduPilot's official apm.pdef.xml into ParamDefinitions."""
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        raise ValueError("refusing apm.pdef.xml that declares a DTD/entities")
    root = ET.fromstring(xml_text)
    vehicle_types = [vehicle_type]
    definitions: dict[str, ParamDefinition] = {}
    for param in root.iter("param"):
        name = param.get("name", "").split(":")[-1]
        if not name:
            continue
        fields = {f.get("name"): (f.text or "").strip() for f in param.findall("field")}
        min_value = max_value = None
        if fields.get("Range"):
            low, _, high = fields["Range"].partition(" ")
            try:
                min_value, max_value = float(low), float(high)
            except ValueError:
                pass
        bitmask = None
        if fields.get("Bitmask"):
            bitmask = {}
            for item in fields["Bitmask"].split(","):
                bit, sep, label = item.partition(":")
                if sep and bit.strip().lstrip("-").isdigit():
                    bitmask[int(bit)] = label.strip()
        values = {v.get("code"): (v.text or "").strip() for v in param.iter("value") if v.get("code") is not None} or None
        increment = None
        if fields.get("Increment"):
            try:
                increment = float(fields["Increment"])
            except ValueError:
                pass
        definitions[name] = ParamDefinition(
            name=name,
            vehicle_types=vehicle_types,
            firmware_version=firmware_version,
            description=param.get("documentation", ""),
            unit=fields.get("Units") or None,
            min_value=min_value,
            max_value=max_value,
            increment=increment,
            bitmask=bitmask or None,
            reboot_required=fields.get("RebootRequired", "").lower() == "true",
            values=values,
            doc_url=param_doc_url(name, vehicle_types),
        )
    return definitions
