"""Normalized, replaceable vulnerability-intelligence source clients.

OSV is the primary package-aware truth. GitHub and NVD may enrich a correlated advisory, but
never remove OSV affected-package evidence or replace it with a secondary source's range.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from itertools import product
import math
import re
from typing import Generic, Iterable, Mapping, TypeVar
from urllib.parse import quote, unquote, urlencode, urlsplit

from .http import HttpRequestError, RetryingHttpClient
from .models import (
    Advisory, AdvisoryEnrichment, AffectedEvent, AffectedEventKind, AffectedPackage, AffectedRange, PackageRef,
    SourceState, SourceStatus,
)


T = TypeVar("T")
_CVE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)
_GHSA = re.compile(r"^GHSA-[A-Z0-9-]+$", re.IGNORECASE)
_EVENT_KINDS = {item.value: item for item in AffectedEventKind}


@dataclass(frozen=True)
class SourceResult(Generic[T]):
    """Return source data with explicit availability evidence.

    An empty ``OK`` value is a completed no-match. ``PARTIAL`` retains data already verified;
    this distinction keeps a later failure from erasing security evidence found earlier.
    """

    value: T
    status: SourceStatus


def _status(source: str, state: SourceState, diagnostic: str = "", provenance: str = "") -> SourceStatus:
    return SourceStatus(source=source, state=state, diagnostic=diagnostic, provenance=provenance)


def _identifiers(record: Mapping[str, object], include: Iterable[str] = ()) -> set[str]:
    values = {str(value).strip().upper() for value in include if str(value).strip()}
    for key in ("id", "ghsa_id", "cve_id"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            values.add(value.strip().upper())
    for item in record.get("aliases", ()) if isinstance(record.get("aliases"), list) else ():
        if isinstance(item, str) and item.strip():
            values.add(item.strip().upper())
    for item in record.get("identifiers", ()) if isinstance(record.get("identifiers"), list) else ():
        if isinstance(item, Mapping) and isinstance(item.get("value"), str) and item["value"].strip():
            values.add(item["value"].strip().upper())
    return values


def _severity_rank(value: str) -> int:
    return {"unknown": 0, "low": 1, "medium": 2, "moderate": 2, "high": 3, "critical": 4}.get(value.lower(), 0)


def _severity_values(value: object) -> list[str]:
    if isinstance(value, Mapping):
        return [item for key in ("severity", "baseSeverity", "score") for item in _severity_values(value.get(key))]
    if isinstance(value, (list, tuple)):
        return [item for member in value for item in _severity_values(member)]
    if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+)?", value.strip())):
        score = float(value)
        return ["critical" if score >= 9 else "high" if score >= 7 else "medium" if score >= 4 else "low" if score > 0 else "unknown"]
    if isinstance(value, str) and value.strip().lower() in {"unknown", "low", "medium", "moderate", "high", "critical"}:
        normalized = value.strip().lower()
        return ["medium" if normalized == "moderate" else normalized]
    return []


def _normalized_severity(*values: object) -> str:
    candidates = [candidate for value in values for candidate in _severity_values(value)]
    return max(candidates, key=_severity_rank, default="unknown")


def _round_up(value: float) -> float:
    return float((Decimal(str(value)) * 10).to_integral_value(rounding=ROUND_CEILING) / 10)


def _parse_cvss(vector: str, version: str, required: set[str], allowed: Mapping[str, set[str]]) -> dict[str, str]:
    """Strictly parse one CVSS vector so malformed source evidence cannot look authoritative."""

    prefix = f"CVSS:{version}"
    parts = vector.split("/")
    if not parts or parts[0] != prefix:
        raise ValueError(f"invalid CVSS {version} vector prefix")
    metrics: dict[str, str] = {}
    for part in parts[1:]:
        if part.count(":") != 1:
            raise ValueError(f"invalid CVSS {version} metric")
        key, value = part.split(":", 1)
        if key in metrics or key not in allowed or value not in allowed[key]:
            raise ValueError(f"invalid CVSS {version} metric {key}")
        metrics[key] = value
    if not required.issubset(metrics):
        raise ValueError(f"CVSS {version} vector lacks required metrics")
    return metrics


def _cvss2_score(vector: str) -> float:
    allowed = {
        "AV": {"L", "A", "N"}, "AC": {"H", "M", "L"}, "Au": {"M", "S", "N"},
        "C": {"N", "P", "C"}, "I": {"N", "P", "C"}, "A": {"N", "P", "C"},
        "E": {"U", "POC", "F", "H", "ND"}, "RL": {"OF", "TF", "W", "U", "ND"},
        "RC": {"UC", "UR", "C", "ND"}, "CDP": {"N", "L", "LM", "MH", "H", "ND"},
        "TD": {"N", "L", "M", "H", "ND"}, "CR": {"L", "M", "H", "ND"},
        "IR": {"L", "M", "H", "ND"}, "AR": {"L", "M", "H", "ND"},
    }
    metrics = _parse_cvss(vector, "2.0", {"AV", "AC", "Au", "C", "I", "A"}, allowed)
    impact = 10.41 * (1 - (1 - {"N": 0, "P": .275, "C": .66}[metrics["C"]])
                      * (1 - {"N": 0, "P": .275, "C": .66}[metrics["I"]])
                      * (1 - {"N": 0, "P": .275, "C": .66}[metrics["A"]]))
    exploitability = 20 * {"L": .395, "A": .646, "N": 1}[metrics["AV"]] \
        * {"H": .35, "M": .61, "L": .71}[metrics["AC"]] \
        * {"M": .45, "S": .56, "N": .704}[metrics["Au"]]
    score = ((.6 * impact) + (.4 * exploitability) - 1.5) * (0 if impact == 0 else 1.176)
    return float(Decimal(str(max(0, score))).quantize(Decimal(".1"), rounding=ROUND_HALF_UP))


def _cvss3_score(vector: str, version: str) -> float:
    allowed = {
        "AV": {"N", "A", "L", "P"}, "AC": {"L", "H"}, "PR": {"N", "L", "H"},
        "UI": {"N", "R"}, "S": {"U", "C"}, "C": {"N", "L", "H"},
        "I": {"N", "L", "H"}, "A": {"N", "L", "H"},
        "E": {"X", "U", "P", "F", "H"}, "RL": {"X", "O", "T", "W", "U"},
        "RC": {"X", "U", "R", "C"}, "CR": {"X", "L", "M", "H"},
        "IR": {"X", "L", "M", "H"}, "AR": {"X", "L", "M", "H"},
        "MAV": {"X", "N", "A", "L", "P"}, "MAC": {"X", "L", "H"},
        "MPR": {"X", "N", "L", "H"}, "MUI": {"X", "N", "R"}, "MS": {"X", "U", "C"},
        "MC": {"X", "N", "L", "H"}, "MI": {"X", "N", "L", "H"}, "MA": {"X", "N", "L", "H"},
    }
    metrics = _parse_cvss(vector, version, {"AV", "AC", "PR", "UI", "S", "C", "I", "A"}, allowed)
    scope = metrics["S"]
    impact_weight = {"N": 0, "L": .22, "H": .56}
    isc = 1 - _product_value(1 - impact_weight[metrics[key]] for key in ("C", "I", "A"))
    impact = 6.42 * isc if scope == "U" else 7.52 * (isc - .029) - 3.25 * (isc - .02) ** 15
    privilege = ({"N": .85, "L": .62, "H": .27} if scope == "U" else {"N": .85, "L": .68, "H": .50})[metrics["PR"]]
    exploitability = 8.22 * {"N": .85, "A": .62, "L": .55, "P": .2}[metrics["AV"]] \
        * {"L": .77, "H": .44}[metrics["AC"]] * privilege * {"N": .85, "R": .62}[metrics["UI"]]
    if impact <= 0:
        return 0.0
    return _round_up(min(10, (1 if scope == "U" else 1.08) * (impact + exploitability)))


def _product_value(values: Iterable[float]) -> float:
    """Multiply a short metric sequence without adding a non-standard dependency."""

    result = 1.0
    for value in values:
        result *= value
    return result


# CVSS v4 macrovector data follows FIRST's BSD-2-Clause reference calculator.
# Copyright FIRST, Red Hat, and contributors; https://github.com/FIRSTdotorg/cvss-v4-calculator
_CVSS4_SCORES = {
    key: float(value) for item in (
        "000000:10,000001:9.9,000010:9.8,000011:9.5,000020:9.5,000021:9.2,000100:10,000101:9.6,000110:9.3,000111:8.7,000120:9.1,000121:8.1,000200:9.3,000201:9,000210:8.9,000211:8,000220:8.1,000221:6.8,001000:9.8,001001:9.5,001010:9.5,001011:9.2,001020:9,001021:8.4,001100:9.3,001101:9.2,001110:8.9,001111:8.1,001120:8.1,001121:6.5,001200:8.8,001201:8,001210:7.8,001211:7,001220:6.9,001221:4.8,002001:9.2,002011:8.2,002021:7.2,002101:7.9,002111:6.9,002121:5,002201:6.9,002211:5.5,002221:2.7,010000:9.9,010001:9.7,010010:9.5,010011:9.2,010020:9.2,010021:8.5,010100:9.5,010101:9.1,010110:9,010111:8.3,010120:8.4,010121:7.1,010200:9.2,010201:8.1,010210:8.2,010211:7.1,010220:7.2,010221:5.3,011000:9.5,011001:9.3,011010:9.2,011011:8.5,011020:8.5,011021:7.3,011100:9.2,011101:8.2,011110:8,011111:7.2,011120:7,011121:5.9,011200:8.4,011201:7,011210:7.1,011211:5.2,011220:5,011221:3,012001:8.6,012011:7.5,012021:5.2,012101:7.1,012111:5.2,012121:2.9,012201:6.3,012211:2.9,012221:1.7,100000:9.8,100001:9.5,100010:9.4,100011:8.7,100020:9.1,100021:8.1,100100:9.4,100101:8.9,100110:8.6,100111:7.4,100120:7.7,100121:6.4,100200:8.7,100201:7.5,100210:7.4,100211:6.3,100220:6.3,100221:4.9,101000:9.4,101001:8.9,101010:8.8,101011:7.7,101020:7.6,101021:6.7,101100:8.6,101101:7.6,101110:7.4,101111:5.8,101120:5.9,101121:5,101200:7.2,101201:5.7,101210:5.7,101211:5.2,101220:5.2,101221:2.5,102001:8.3,102011:7,102021:5.4,102101:6.5,102111:5.8,102121:2.6,102201:5.3,102211:2.1,102221:1.3,110000:9.5,110001:9,110010:8.8,110011:7.6,110020:7.6,110021:7,110100:9,110101:7.7,110110:7.5,110111:6.2,110120:6.1,110121:5.3,110200:7.7,110201:6.6,110210:6.8,110211:5.9,110220:5.2,110221:3,111000:8.9,111001:7.8,111010:7.6,111011:6.7,111020:6.2,111021:5.8,111100:7.4,111101:5.9,111110:5.7,111111:5.7,111120:4.7,111121:2.3,111200:6.1,111201:5.2,111210:5.7,111211:2.9,111220:2.4,111221:1.6,112001:7.1,112011:5.9,112021:3,112101:5.8,112111:2.6,112121:1.5,112201:2.3,112211:1.3,112221:0.6,200000:9.3,200001:8.7,200010:8.6,200011:7.2,200020:7.5,200021:5.8,200100:8.6,200101:7.4,200110:7.4,200111:6.1,200120:5.6,200121:3.4,200200:7,200201:5.4,200210:5.2,200211:4,200220:4,200221:2.2,201000:8.5,201001:7.5,201010:7.4,201011:5.5,201020:6.2,201021:5.1,201100:7.2,201101:5.7,201110:5.5,201111:4.1,201120:4.6,201121:1.9,201200:5.3,201201:3.6,201210:3.4,201211:1.9,201220:1.9,201221:0.8,202001:6.4,202011:5.1,202021:2,202101:4.7,202111:2.1,202121:1.1,202201:2.4,202211:0.9,202221:0.4,210000:8.8,210001:7.5,210010:7.3,210011:5.3,210020:6,210021:5,210100:7.3,210101:5.5,210110:5.9,210111:4,210120:4.1,210121:2,210200:5.4,210201:4.3,210210:4.5,210211:2.2,210220:2,210221:1.1,211000:7.5,211001:5.5,211010:5.8,211011:4.5,211020:4,211021:2.1,211100:6.1,211101:5.1,211110:4.8,211111:1.8,211120:2,211121:0.9,211200:4.6,211201:1.8,211210:1.7,211211:0.7,211220:0.8,211221:0.2,212001:5.3,212011:2.4,212021:1.4,212101:2.4,212111:1.2,212121:0.5,212201:1,212211:0.3,212221:0.1"
    ).split(",") for key, value in (item.split(":", 1),)
}
_CVSS4_DISTANCES = {
    "AV": {"N": 0, "A": 1, "L": 2, "P": 3}, "PR": {"N": 0, "L": 1, "H": 2},
    "UI": {"N": 0, "P": 1, "A": 2}, "AC": {"L": 0, "H": 1}, "AT": {"N": 0, "P": 1},
    "VC": {"H": 0, "L": 1, "N": 2}, "VI": {"H": 0, "L": 1, "N": 2},
    "VA": {"H": 0, "L": 1, "N": 2}, "SC": {"H": 1, "L": 2, "N": 3},
    "SI": {"S": 0, "H": 1, "L": 2, "N": 3}, "SA": {"S": 0, "H": 1, "L": 2, "N": 3},
    "CR": {"H": 0, "M": 1, "L": 2}, "IR": {"H": 0, "M": 1, "L": 2},
    "AR": {"H": 0, "M": 1, "L": 2}, "E": {"U": 2, "P": 1, "A": 0},
}
_CVSS4_MAXES = {
    "eq1": {
        "0": ("AV:N/PR:N/UI:N",),
        "1": ("AV:A/PR:N/UI:N", "AV:N/PR:L/UI:N", "AV:N/PR:N/UI:P"),
        "2": ("AV:P/PR:N/UI:N", "AV:A/PR:L/UI:P"),
    },
    "eq2": {"0": ("AC:L/AT:N",), "1": ("AC:H/AT:N", "AC:L/AT:P")},
    "eq36": {
        "00": ("VC:H/VI:H/VA:H/CR:H/IR:H/AR:H",),
        "01": ("VC:H/VI:H/VA:L/CR:M/IR:M/AR:H", "VC:H/VI:H/VA:H/CR:M/IR:M/AR:M"),
        "10": ("VC:L/VI:H/VA:H/CR:H/IR:H/AR:H", "VC:H/VI:L/VA:H/CR:H/IR:H/AR:H"),
        "11": ("VC:L/VI:H/VA:L/CR:H/IR:M/AR:H", "VC:L/VI:H/VA:H/CR:H/IR:M/AR:M",
               "VC:H/VI:L/VA:H/CR:M/IR:H/AR:M", "VC:H/VI:L/VA:L/CR:M/IR:H/AR:H",
               "VC:L/VI:L/VA:H/CR:H/IR:H/AR:M"),
        "21": ("VC:L/VI:L/VA:L/CR:H/IR:H/AR:H",),
    },
    "eq4": {"0": ("SC:H/SI:S/SA:S",), "1": ("SC:H/SI:H/SA:H",), "2": ("SC:L/SI:L/SA:L",)},
    "eq5": {"0": ("E:A",), "1": ("E:P",), "2": ("E:U",)},
}
_CVSS4_MAX_DISTANCE = {
    "eq1": {"0": 1, "1": 4, "2": 5}, "eq2": {"0": 1, "1": 2},
    "eq36": {"00": 7, "01": 6, "10": 8, "11": 8, "21": 10},
    "eq4": {"0": 6, "1": 5, "2": 4}, "eq5": {"0": 1, "1": 1, "2": 1},
}
_CVSS4_EQ_METRICS = {
    "eq1": ("AV", "PR", "UI"), "eq2": ("AC", "AT"),
    "eq36": ("VC", "VI", "VA", "CR", "IR", "AR"), "eq4": ("SC", "SI", "SA"), "eq5": ("E",),
}


def _cvss4_metrics(vector: str) -> dict[str, str]:
    base = {
        "AV": {"N", "A", "L", "P"}, "AC": {"L", "H"}, "AT": {"N", "P"},
        "PR": {"N", "L", "H"}, "UI": {"N", "P", "A"}, "VC": {"H", "L", "N"},
        "VI": {"H", "L", "N"}, "VA": {"H", "L", "N"}, "SC": {"H", "L", "N"},
        "SI": {"H", "L", "N"}, "SA": {"H", "L", "N"},
    }
    allowed = dict(base)
    allowed.update({
        "E": {"X", "A", "P", "U"}, "CR": {"X", "H", "M", "L"}, "IR": {"X", "H", "M", "L"},
        "AR": {"X", "H", "M", "L"}, "S": {"X", "N", "P"}, "AU": {"X", "N", "Y"},
        "R": {"X", "A", "U", "I"}, "V": {"X", "D", "C"}, "RE": {"X", "L", "M", "H"},
        "U": {"X", "Clear", "Green", "Amber", "Red"},
    })
    for key, values in base.items():
        allowed["M" + key] = {"X", *values}
    allowed["MSI"].add("S")
    allowed["MSA"].add("S")
    metrics = _parse_cvss(vector, "4.0", set(base), allowed)
    for key in tuple(base):
        modified = metrics.get("M" + key)
        if modified and modified != "X":
            metrics[key] = modified
    for key, default in {"E": "A", "CR": "H", "IR": "H", "AR": "H"}.items():
        if metrics.get(key, "X") == "X":
            metrics[key] = default
    return metrics


def _cvss4_macro(metrics: Mapping[str, str]) -> str:
    eq1 = 0 if metrics["AV"] == metrics["PR"] == metrics["UI"] == "N" else (
        1 if metrics["AV"] != "P" and "N" in {metrics["AV"], metrics["PR"], metrics["UI"]} else 2)
    eq2 = 0 if metrics["AC"] == "L" and metrics["AT"] == "N" else 1
    eq3 = 0 if metrics["VC"] == metrics["VI"] == "H" else (
        1 if "H" in {metrics["VC"], metrics["VI"], metrics["VA"]} else 2)
    eq4 = 0 if "S" in {metrics["SI"], metrics["SA"]} else (
        1 if "H" in {metrics["SC"], metrics["SI"], metrics["SA"]} else 2)
    eq5 = {"A": 0, "P": 1, "U": 2}[metrics["E"]]
    eq6 = 0 if any(metrics[requirement] == metrics[impact] == "H"
                   for requirement, impact in (("CR", "VC"), ("IR", "VI"), ("AR", "VA"))) else 1
    return "".join(str(value) for value in (eq1, eq2, eq3, eq4, eq5, eq6))


def _cvss4_score(vector: str) -> float:
    metrics = _cvss4_metrics(vector)
    if all(metrics[key] == "N" for key in ("VC", "VI", "VA", "SC", "SI", "SA")):
        return 0.0
    macro = _cvss4_macro(metrics)
    base_score = _CVSS4_SCORES[macro]
    digits = [int(value) for value in macro]
    lowers = {
        "eq1": f"{digits[0] + 1}{macro[1:]}",
        "eq2": f"{macro[0]}{digits[1] + 1}{macro[2:]}",
        "eq4": f"{macro[:3]}{digits[3] + 1}{macro[4:]}",
        "eq5": f"{macro[:4]}{digits[4] + 1}{macro[5]}",
    }
    pair = macro[2] + macro[5]
    if pair == "00":
        left = f"{macro[:2]}1{macro[3:]}"
        right = f"{macro[:5]}1"
        lowers["eq36"] = max((left, right), key=lambda item: _CVSS4_SCORES[item])
    elif pair in {"01", "11"}:
        lowers["eq36"] = f"{macro[:2]}{digits[2] + 1}{macro[3:]}"
    elif pair == "10":
        lowers["eq36"] = f"{macro[:5]}1"
    else:
        lowers["eq36"] = ""
    candidates = product(*(_CVSS4_MAXES[key][macro[2] + macro[5] if key == "eq36" else macro[int(key[-1]) - 1]]
                           for key in ("eq1", "eq2", "eq36", "eq4", "eq5")))
    distances: dict[str, int] | None = None
    for candidate in candidates:
        maximum = dict(part.split(":", 1) for subvector in candidate for part in subvector.split("/"))
        attempt = {key: _CVSS4_DISTANCES[key][metrics[key]] - _CVSS4_DISTANCES[key][maximum[key]]
                   for key in _CVSS4_DISTANCES}
        if all(value >= 0 for value in attempt.values()):
            distances = attempt
            break
    if distances is None:
        raise ValueError("CVSS 4.0 vector has no scoring macrovector")
    adjustments: list[float] = []
    for eq, eq_metrics in _CVSS4_EQ_METRICS.items():
        lower_score = _CVSS4_SCORES.get(lowers[eq])
        if lower_score is None:
            continue
        key = macro[2] + macro[5] if eq == "eq36" else macro[int(eq[-1]) - 1]
        proportion = sum(distances[item] for item in eq_metrics) / _CVSS4_MAX_DISTANCE[eq][key]
        adjustments.append((base_score - lower_score) * proportion)
    score = base_score - (sum(adjustments) / len(adjustments) if adjustments else 0)
    return float(Decimal(max(0, min(10, score))).quantize(Decimal(".1"), rounding=ROUND_HALF_UP))


def _cvss_score(vector: str) -> float:
    if vector.startswith("AV:"):
        return _cvss2_score(f"CVSS:2.0/{vector}")
    if vector.startswith("CVSS:2.0/"):
        return _cvss2_score(vector)
    if vector.startswith("CVSS:3.0/"):
        return _cvss3_score(vector, "3.0")
    if vector.startswith("CVSS:3.1/"):
        return _cvss3_score(vector, "3.1")
    if vector.startswith("CVSS:4.0/"):
        return _cvss4_score(vector)
    raise ValueError("unsupported CVSS vector version")


def _cvss_version(vector: str) -> str:
    if vector.startswith("AV:") or vector.startswith("CVSS:2.0/"):
        return "2.0"
    if vector.startswith("CVSS:3.0/"):
        return "3.0"
    if vector.startswith("CVSS:3.1/"):
        return "3.1"
    if vector.startswith("CVSS:4.0/"):
        return "4.0"
    raise ValueError("unsupported CVSS vector version")


def _verified_cvss(score: object, vector: object, expected_versions: set[str]) -> tuple[float, str]:
    """Return a finite, version-consistent CVSS pair whose declared score matches its vector."""

    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
        raise ValueError("CVSS score is invalid")
    numeric = float(score)
    if not 0 <= numeric <= 10 or not isinstance(vector, str) or _cvss_version(vector) not in expected_versions:
        raise ValueError("CVSS metric version or domain is invalid")
    calculated = _cvss_score(vector)
    if not math.isclose(numeric, calculated, abs_tol=0.05):
        raise ValueError("CVSS score does not match vector")
    return numeric, vector


def _timestamp(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or "T" not in value:
        raise ValueError("timestamp is invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp is invalid")
    return value


def _is_http_url(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _osv_cvss_evidence(values: Iterable[object], diagnostics: list[str]) -> tuple[tuple[float, ...], tuple[str, ...]]:
    """Calculate valid OSV vectors while recording malformed optional evidence."""

    scores: set[float] = set()
    vectors: set[str] = set()
    for value in values:
        if value is None:
            continue
        if not isinstance(value, list):
            diagnostics.append("OSV severity must be a list")
            continue
        for entry in value:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("type"), str) or not isinstance(entry.get("score"), str):
                diagnostics.append("OSV severity entry is invalid")
                continue
            declared = entry["type"].upper()
            vector = entry["score"]
            expected = {"CVSS_V2": {"2.0"}, "CVSS_V3": {"3.0", "3.1"}, "CVSS_V4": {"4.0"}}.get(declared)
            try:
                if expected is None or _cvss_version(vector) not in expected:
                    raise ValueError
                score = _cvss_score(vector)
            except (KeyError, ValueError):
                diagnostics.append("OSV CVSS type or vector is invalid")
                continue
            scores.add(score)
            vectors.add(vector)
    return tuple(sorted(scores)), tuple(sorted(vectors))


def _purl_parts(purl: str) -> tuple[str, str | None]:
    """Return a decoded purl identity and optional exact version, excluding qualifiers/subpaths."""

    core = purl.split("?", 1)[0].split("#", 1)[0]
    if "@" not in core:
        return unquote(core), None
    identity, version = core.rsplit("@", 1)
    return unquote(identity), unquote(version)


def _canonical_ecosystem(value: str) -> str:
    return {"pip": "pypi", "pypi": "pypi", "rust": "crates.io", "crates.io": "crates.io",
            "go": "go", "golang": "go"}.get(value.casefold(), value.casefold())


def _name_key(ecosystem: str, name: str) -> str:
    canonical = _canonical_ecosystem(ecosystem)
    if canonical == "pypi":
        return re.sub(r"[-_.]+", "-", name).casefold()
    if canonical in {"go", "maven"}:
        return name
    return name.casefold()


def _purl_identity_key(identity: str) -> tuple[str, str]:
    if not identity.casefold().startswith("pkg:") or "/" not in identity:
        return "", identity
    ecosystem, name = identity[4:].split("/", 1)
    canonical = _canonical_ecosystem(ecosystem)
    return canonical, _name_key(canonical, name)


def _matches(package: PackageRef, affected: AffectedPackage) -> bool:
    """Compare package identities exactly; purl versions must decode to the resolved version."""

    if affected.purl:
        affected_identity, affected_version = _purl_parts(affected.purl)
        package_identity, package_version = _purl_parts(package.purl)
        if package_version is not None and package_version != package.version:
            return False
        if _purl_identity_key(affected_identity) != _purl_identity_key(package_identity):
            return False
        return affected_version is None or affected_version == package.version
    return (_canonical_ecosystem(affected.ecosystem), _name_key(affected.ecosystem, affected.name)) == (
        _canonical_ecosystem(package.ecosystem), _name_key(package.ecosystem, package.name))


def _project(advisory: Advisory, package: PackageRef | None) -> Advisory:
    """Populate legacy flat fields only from evidence for one exact resolved package."""

    if package is None:
        return advisory
    matches = [affected for affected in advisory.affected_packages if _matches(package, affected)]
    if not matches:
        if not advisory.affected_packages:
            return advisory
        fixes: tuple[str, ...] = ()
        events: tuple[str, ...] = ()
    else:
        events = tuple(
            f"{event.kind.value}:{event.value}"
            for affected in matches for range_item in affected.ranges for event in range_item.events
        )
        fixes = tuple(sorted({fix for affected in matches for fix in affected.fixed_versions}))
    return Advisory(
        id=advisory.id, aliases=advisory.aliases, severity=advisory.severity,
        withdrawn=advisory.withdrawn, fixed_versions=fixes,
        references=advisory.references, affected_ranges=events, modified=advisory.modified,
        details=advisory.details, source=advisory.source, affected_packages=advisory.affected_packages,
        enrichments=advisory.enrichments,
    )


def _projection_identity(advisory: Advisory) -> tuple[str, str] | None:
    """Identify the one structured package responsible for an advisory's flat projection."""

    if not advisory.fixed_versions and not advisory.affected_ranges:
        return None
    if not advisory.affected_packages:
        return "legacy", advisory.id
    grouped: dict[tuple[str, str], list[AffectedPackage]] = {}
    for affected in advisory.affected_packages:
        if affected.purl:
            identity, _version = _purl_parts(affected.purl)
            key = _purl_identity_key(identity)
        else:
            key = (_canonical_ecosystem(affected.ecosystem), _name_key(affected.ecosystem, affected.name))
        grouped.setdefault(key, []).append(affected)
    if len(grouped) == 1:
        return next(iter(grouped))
    matches: list[tuple[str, str]] = []
    for key, affected_items in grouped.items():
        events = tuple(f"{event.kind.value}:{event.value}" for affected in affected_items
                       for range_item in affected.ranges for event in range_item.events)
        fixes = {fix for affected in affected_items for fix in affected.fixed_versions}
        ranges_match = not advisory.affected_ranges or advisory.affected_ranges == events
        fixes_match = not fixes or fixes.issubset(advisory.fixed_versions)
        if ranges_match and fixes_match:
            matches.append(key)
    return matches[0] if len(matches) == 1 else None


def _merge(primary: Advisory, secondary: Advisory, package: PackageRef | None = None) -> Advisory:
    """Add secondary metadata while retaining primary OSV package evidence unchanged."""

    projected_primary = _project(primary, package)
    projected_secondary = _project(secondary, package)
    merged = Advisory(
        id=projected_primary.id,
        aliases=tuple(sorted(set(primary.aliases) | set(secondary.aliases) | {primary.id, secondary.id})),
        severity=_normalized_severity(projected_primary.severity, secondary.severity),
        withdrawn=projected_primary.withdrawn or secondary.withdrawn,
        fixed_versions=tuple(sorted(set(projected_primary.fixed_versions) | set(projected_secondary.fixed_versions))),
        references=tuple(sorted(set(primary.references) | set(secondary.references))),
        affected_ranges=projected_primary.affected_ranges,
        modified=secondary.modified or primary.modified,
        details=primary.details or secondary.details,
        source=";".join(sorted(set(filter(None, (primary.source, secondary.source))))),
        affected_packages=projected_primary.affected_packages,
        enrichments=tuple(sorted(set(projected_primary.enrichments) | set(secondary.enrichments), key=lambda item: item.source)),
    )
    return _project(merged, package) if not merged.fixed_versions and package is not None else merged


class OsvClient:
    """Query OSV as the primary ecosystem-aware matcher and preserve every affected package."""

    endpoint = "https://api.osv.dev/v1"

    def __init__(self, http: RetryingHttpClient, *, max_pages: int = 10) -> None:
        """Use the injected bounded HTTP client and cap hostile pagination chains."""
        self.http = http
        self.max_pages = max(1, max_pages)

    def query(self, packages: Iterable[PackageRef]) -> SourceResult[list[Advisory]]:
        """Return complete OSV records for exact package versions with partial retention.

        A versioned purl is used only when its decoded version exactly matches the resolved
        version; otherwise OSV receives ecosystem/name plus that explicit version.
        """

        active = [(self._package_query(package), package) for package in packages]
        if not active:
            return SourceResult([], _status("osv", SourceState.OK, provenance="no packages"))
        # OSV's query endpoint returns source-canonical spelling while its record endpoint is
        # case-sensitive for identifiers such as GHSA IDs.  Keep a normalized key for stable
        # deduplication, but retain the first raw spelling for the transport lookup.
        ids: dict[str, tuple[str, set[PackageRef]]] = {}
        partial = False
        successful_page = False
        diagnostic = ""
        for _page in range(self.max_pages):
            payload_queries = [query for query, _package in active]
            try:
                payload = self.http.request_json("POST", f"{self.endpoint}/querybatch", payload={"queries": payload_queries})
            except HttpRequestError as error:
                diagnostic = self.http.last_diagnostic or str(error)
                if not successful_page:
                    return SourceResult([], _status("osv", SourceState.UNAVAILABLE, diagnostic, self.endpoint))
                partial = True
                break
            successful_page = True
            if not isinstance(payload, Mapping) or not isinstance(payload.get("results"), list):
                partial = True
                diagnostic = "OSV querybatch response lacks results"
                break
            results = payload["results"]
            if len(results) != len(active):
                partial = True
            next_active: list[tuple[dict[str, object], PackageRef]] = []
            for (query, package), result in zip(active, results):
                if not isinstance(result, Mapping) or not isinstance(result.get("vulns", []), list):
                    partial = True
                    continue
                for vulnerability in result.get("vulns", []):
                    if not isinstance(vulnerability, Mapping) or not isinstance(vulnerability.get("id"), str):
                        partial = True
                        continue
                    raw_identifier = vulnerability["id"].strip()
                    normalized_identifier = raw_identifier.upper()
                    if not raw_identifier:
                        partial = True
                        continue
                    if normalized_identifier not in ids:
                        ids[normalized_identifier] = (raw_identifier, set())
                    ids[normalized_identifier][1].add(package)
                token = result.get("next_page_token")
                if token is not None and not isinstance(token, str):
                    partial = True
                elif token:
                    paged = dict(query)
                    paged["page_token"] = token
                    next_active.append((paged, package))
            if not next_active:
                active = []
                break
            active = next_active
        if active:
            partial = True
            diagnostic = diagnostic or "OSV pagination limit reached"

        records: list[Advisory] = []
        for _normalized_identifier, (identifier, matched_packages) in sorted(ids.items()):
            bound = next(iter(matched_packages)) if len(matched_packages) == 1 else None
            fetched = self.lookup(identifier, package=bound)
            if fetched.value is not None:
                records.append(fetched.value)
            if fetched.value is None or fetched.status.state is not SourceState.OK:
                partial = True
                diagnostic = diagnostic or fetched.status.diagnostic or "OSV advisory lookup returned no record"
        return SourceResult(records, _status("osv", SourceState.PARTIAL if partial else SourceState.OK,
                                             diagnostic, self.endpoint))

    def lookup(self, identifier: str, *, package: PackageRef | None = None) -> SourceResult[Advisory | None]:
        """Fetch one complete OSV record by stable identifier and optionally project one package."""
        try:
            payload = self.http.request_json("GET", f"{self.endpoint}/vulns/{quote(identifier, safe='-')}")
        except HttpRequestError as error:
            if error.status == 404:
                return SourceResult(None, _status("osv", SourceState.OK, provenance=self.endpoint))
            return SourceResult(None, _status("osv", SourceState.UNAVAILABLE, self.http.last_diagnostic or str(error), self.endpoint))
        if not isinstance(payload, Mapping) or not isinstance(payload.get("id"), str):
            return SourceResult(None, _status("osv", SourceState.PARTIAL, "OSV record lacks string id", self.endpoint))
        if payload["id"].strip().upper() != identifier.strip().upper():
            return SourceResult(None, _status("osv", SourceState.PARTIAL, "OSV response id does not match request", self.endpoint))
        try:
            diagnostics: list[str] = []
            advisory = _project(self.normalize(payload, diagnostics=diagnostics), package)
            return SourceResult(advisory, _status("osv", SourceState.PARTIAL if diagnostics else SourceState.OK,
                                                   "; ".join(sorted(set(diagnostics))), self.endpoint))
        except ValueError as error:
            return SourceResult(None, _status("osv", SourceState.PARTIAL, str(error), self.endpoint))

    def normalize(self, record: Mapping[str, object], *, diagnostics: list[str] | None = None) -> Advisory:
        """Normalize OSV records without pooling package evidence.

        Optional ``diagnostics`` receives malformed non-core evidence so lookup callers can
        return ``PARTIAL`` without discarding the otherwise usable advisory.
        """
        evidence_diagnostics = diagnostics if diagnostics is not None else []
        raw_affected = record.get("affected", [])
        if not isinstance(raw_affected, list):
            raise ValueError("OSV affected must be a list")
        affected_packages: list[AffectedPackage] = []
        severity_values: list[object] = []
        severity_arrays: list[object] = [record.get("severity")]
        database = record.get("database_specific")
        if isinstance(database, Mapping):
            database_severity = database.get("severity")
            if database_severity is not None and not _severity_values(database_severity):
                evidence_diagnostics.append("OSV database severity is unknown")
            else:
                severity_values.append(database_severity)
        elif database is not None:
            evidence_diagnostics.append("OSV database_specific is invalid")
        for item in raw_affected:
            if not isinstance(item, Mapping) or not isinstance(item.get("package"), Mapping):
                raise ValueError("OSV affected entry lacks package")
            package = item["package"]
            ecosystem, name = package.get("ecosystem"), package.get("name")
            if not isinstance(ecosystem, str) or not isinstance(name, str) or not ecosystem or not name:
                raise ValueError("OSV affected package lacks ecosystem/name")
            purl = package.get("purl")
            if purl is not None and not isinstance(purl, str):
                raise ValueError("OSV affected package purl is invalid")
            versions = item.get("versions", [])
            ranges = item.get("ranges", [])
            if not isinstance(versions, list) or not all(isinstance(value, str) for value in versions):
                raise ValueError("OSV affected versions are invalid")
            if not isinstance(ranges, list):
                raise ValueError("OSV affected ranges are invalid")
            parsed_ranges: list[AffectedRange] = []
            fixes: set[str] = set()
            for range_item in ranges:
                if not isinstance(range_item, Mapping) or not isinstance(range_item.get("type"), str):
                    raise ValueError("OSV range lacks type")
                events = range_item.get("events", [])
                if not isinstance(events, list):
                    raise ValueError("OSV range events are invalid")
                parsed_events: list[AffectedEvent] = []
                for event in events:
                    if not isinstance(event, Mapping):
                        raise ValueError("OSV range event is invalid")
                    keys = [key for key in _EVENT_KINDS if isinstance(event.get(key), str) and event[key]]
                    if len(keys) != 1:
                        raise ValueError("OSV range event must have one transition")
                    key = keys[0]
                    value = str(event[key])
                    parsed_events.append(AffectedEvent(_EVENT_KINDS[key], value))
                    if key == AffectedEventKind.FIXED.value:
                        fixes.add(value)
                repo = range_item.get("repo")
                if repo is not None and not isinstance(repo, str):
                    raise ValueError("OSV range repo is invalid")
                parsed_ranges.append(AffectedRange(type=range_item["type"], events=tuple(parsed_events), repo=repo))
            ecosystem_specific = item.get("ecosystem_specific")
            if isinstance(ecosystem_specific, Mapping):
                ecosystem_severity = ecosystem_specific.get("severity")
                if ecosystem_severity is not None and not _severity_values(ecosystem_severity):
                    evidence_diagnostics.append("OSV ecosystem severity is unknown")
                else:
                    severity_values.append(ecosystem_severity)
            elif ecosystem_specific is not None:
                evidence_diagnostics.append("OSV ecosystem_specific is invalid")
            severity_arrays.append(item.get("severity"))
            affected_packages.append(AffectedPackage(ecosystem, name, purl, tuple(versions), tuple(parsed_ranges), tuple(sorted(fixes))))
        references = record.get("references", [])
        if not isinstance(references, list):
            evidence_diagnostics.append("OSV references are invalid")
            references = []
        urls: list[str] = []
        for item in references:
            if not isinstance(item, Mapping) or not _is_http_url(item.get("url")):
                evidence_diagnostics.append("OSV reference URL is invalid")
            else:
                urls.append(item["url"])
        aliases = record.get("aliases", [])
        if not isinstance(aliases, list):
            evidence_diagnostics.append("OSV aliases are invalid")
            aliases = []
        elif not all(isinstance(alias, str) and alias.strip() for alias in aliases):
            evidence_diagnostics.append("OSV alias is invalid")
            aliases = [alias for alias in aliases if isinstance(alias, str) and alias.strip()]
        identifier = str(record["id"]).strip().upper()
        cvss_scores, cvss_vectors = _osv_cvss_evidence(severity_arrays, evidence_diagnostics)
        severity = _normalized_severity(*severity_values, *cvss_scores)
        withdrawn_value = record.get("withdrawn")
        try:
            withdrawn_value = _timestamp(withdrawn_value)
        except ValueError:
            evidence_diagnostics.append("OSV withdrawn timestamp is invalid")
            withdrawn_value = None
        modified = record.get("modified")
        try:
            modified = _timestamp(modified)
        except ValueError:
            evidence_diagnostics.append("OSV modified timestamp is invalid")
            modified = None
        enrichments = (AdvisoryEnrichment(source="osv", severity=severity,
                                           cvss_scores=cvss_scores, cvss_vectors=cvss_vectors),) if cvss_vectors else ()
        return Advisory(id=identifier, aliases=tuple(sorted({alias.strip().upper() for alias in aliases} - {identifier})),
                        severity=severity, withdrawn=withdrawn_value is not None,
                        references=tuple(sorted(urls)), modified=modified,
                        details=str(record.get("details", "")), source="osv", affected_packages=tuple(affected_packages),
                        enrichments=enrichments)

    @staticmethod
    def _package_query(package: PackageRef) -> dict[str, object]:
        _identity, purl_version = _purl_parts(package.purl)
        if purl_version == package.version:
            return {"package": {"purl": package.purl}}
        return {"package": {"ecosystem": package.ecosystem, "name": package.name}, "version": package.version}


class GithubClient:
    """Enrich an OSV advisory from GitHub without changing OSV affected-package truth."""
    endpoint = "https://api.github.com/advisories"
    api_version = "2026-03-10"

    def __init__(self, http: RetryingHttpClient) -> None:
        """Use the common bounded client and its retry/redaction boundary."""
        self.http = http

    def enrich(self, advisory: Advisory, *, package: PackageRef | None = None) -> SourceResult[Advisory]:
        """Add GitHub evidence using deterministic GHSA-first alias and exact-package selection.

        Sorting normalized candidates keeps source requests reproducible across hash seeds while
        GHSA preference avoids letting incidental alias order choose a less-specific CVE lookup.
        """
        identifiers = sorted({item.strip().upper() for item in (advisory.id, *advisory.aliases) if item.strip()})
        identifier = next((item for item in identifiers if _GHSA.fullmatch(item)), None)
        identifier = identifier or next((item for item in identifiers if _CVE.fullmatch(item)), None)
        if not identifier:
            return SourceResult(advisory, _status("github", SourceState.NOT_APPLICABLE, provenance=self.endpoint))
        fetched = self.lookup(identifier)
        if fetched.value is None:
            return SourceResult(advisory, fetched.status)
        return SourceResult(_merge(advisory, fetched.value, package), fetched.status)

    def lookup(self, identifier: str) -> SourceResult[Advisory | None]:
        """Look up one GHSA or CVE; malformed remote schemas are partial, never empty success."""
        normalized = identifier.strip().upper()
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": self.api_version}
        if _GHSA.fullmatch(normalized):
            url = f"{self.endpoint}/{quote(normalized, safe='-')}"
        elif _CVE.fullmatch(normalized):
            url = f"{self.endpoint}?{urlencode({'cve_id': normalized})}"
        else:
            return SourceResult(None, _status("github", SourceState.NOT_APPLICABLE, "invalid advisory identifier", self.endpoint))
        try:
            payload = self.http.request_json("GET", url, headers=headers)
        except HttpRequestError as error:
            if error.status == 404:
                return SourceResult(None, _status("github", SourceState.OK, provenance=self.endpoint))
            return SourceResult(None, _status("github", SourceState.UNAVAILABLE, self.http.last_diagnostic or str(error), self.endpoint))
        if isinstance(payload, list) and not payload:
            return SourceResult(None, _status("github", SourceState.OK, provenance=self.endpoint))
        record = payload[0] if isinstance(payload, list) and len(payload) == 1 else payload
        if not isinstance(record, Mapping):
            return SourceResult(None, _status("github", SourceState.PARTIAL, "invalid GitHub advisory schema", self.endpoint))
        response_ids = _identifiers(record)
        if (_GHSA.fullmatch(normalized) and normalized != str(record.get("ghsa_id", "")).strip().upper()) or (
                _CVE.fullmatch(normalized) and normalized not in response_ids):
            return SourceResult(None, _status("github", SourceState.PARTIAL,
                                              "GitHub response id does not match request", self.endpoint))
        try:
            diagnostics: list[str] = []
            advisory = self._normalize(record, diagnostics=diagnostics)
            return SourceResult(advisory, _status("github", SourceState.PARTIAL if diagnostics else SourceState.OK,
                                                   "; ".join(sorted(set(diagnostics))), self.endpoint))
        except ValueError as error:
            return SourceResult(None, _status("github", SourceState.PARTIAL, str(error), self.endpoint))

    @staticmethod
    def _normalize(record: Mapping[str, object], *, diagnostics: list[str] | None = None) -> Advisory:
        """Normalize core GitHub evidence and report malformed optional metrics separately."""
        evidence_diagnostics = diagnostics if diagnostics is not None else []
        ghsa = record.get("ghsa_id")
        vulnerabilities = record.get("vulnerabilities")
        if not isinstance(ghsa, str) or not _GHSA.fullmatch(ghsa) or not isinstance(vulnerabilities, list):
            raise ValueError("GitHub advisory lacks ghsa_id or vulnerabilities")
        affected: list[AffectedPackage] = []
        vulnerable_functions: set[str] = set()
        for item in vulnerabilities:
            if not isinstance(item, Mapping) or not isinstance(item.get("package"), Mapping):
                raise ValueError("GitHub vulnerability lacks package")
            package = item["package"]
            ecosystem, name = package.get("ecosystem"), package.get("name")
            patched = item.get("first_patched_version")
            if not isinstance(ecosystem, str) or not isinstance(name, str) or (patched is not None and not isinstance(patched, str)):
                raise ValueError("GitHub vulnerability fields are invalid")
            affected.append(AffectedPackage(ecosystem, name, fixed_versions=(patched,) if patched else ()))
            functions = item.get("vulnerable_functions", [])
            if functions is not None and (not isinstance(functions, list) or not all(isinstance(value, str) for value in functions)):
                raise ValueError("GitHub vulnerable functions are invalid")
            vulnerable_functions.update(functions or [])
        identifiers = _identifiers(record)
        canonical = ghsa.upper()
        references = record.get("references", [])
        if not isinstance(references, list):
            evidence_diagnostics.append("GitHub references are invalid")
            references = []
        valid_references: list[str] = []
        for reference in references:
            if not _is_http_url(reference):
                evidence_diagnostics.append("GitHub reference URL is invalid")
            else:
                valid_references.append(reference)
        cvss = record.get("cvss")
        cvss_severities = record.get("cvss_severities")
        if cvss is not None and not isinstance(cvss, Mapping):
            evidence_diagnostics.append("GitHub CVSS is invalid")
            cvss = None
        if cvss_severities is not None and not isinstance(cvss_severities, Mapping):
            evidence_diagnostics.append("GitHub CVSS severities are invalid")
            cvss_severities = {}
        cvss_scores: set[float] = set()
        cvss_vectors: set[str] = set()
        candidates: list[tuple[set[str], object]] = [({"3.0", "3.1"}, cvss)] if cvss is not None else []
        for label, candidate in (cvss_severities or {}).items():
            expected = {"cvss_v3": {"3.0", "3.1"}, "cvss_v4": {"4.0"}}.get(str(label).lower())
            if expected is None:
                evidence_diagnostics.append("GitHub CVSS container version is invalid")
                continue
            candidates.append((expected, candidate))
        for expected, candidate in candidates:
            if candidate is None:
                continue
            if not isinstance(candidate, Mapping):
                evidence_diagnostics.append("GitHub CVSS metric is invalid")
                continue
            score, vector = candidate.get("score"), candidate.get("vector_string")
            try:
                verified_score, verified_vector = _verified_cvss(score, vector, expected)
            except (KeyError, ValueError):
                evidence_diagnostics.append("GitHub CVSS metric is invalid")
                continue
            cvss_scores.add(verified_score)
            cvss_vectors.add(verified_vector)
        epss_scores: set[float] = set()
        if record.get("epss") is not None and not isinstance(record.get("epss"), Mapping):
            evidence_diagnostics.append("GitHub EPSS is invalid")
        if isinstance(record.get("epss"), Mapping):
            for key in ("percentage", "percentile"):
                value = record["epss"].get(key)
                if value is None:
                    continue
                try:
                    numeric = float(value) if not isinstance(value, bool) else math.nan
                except (TypeError, ValueError):
                    evidence_diagnostics.append("GitHub EPSS score is invalid")
                    continue
                if not math.isfinite(numeric) or not 0 <= numeric <= 1:
                    evidence_diagnostics.append("GitHub EPSS score is invalid")
                    continue
                epss_scores.add(numeric)
        withdrawn_at = record.get("withdrawn_at")
        try:
            withdrawn_at = _timestamp(withdrawn_at)
        except ValueError:
            evidence_diagnostics.append("GitHub withdrawn_at timestamp is invalid")
            withdrawn_at = None
        updated_at = record.get("updated_at")
        try:
            updated_at = _timestamp(updated_at)
        except ValueError:
            evidence_diagnostics.append("GitHub updated_at timestamp is invalid")
            updated_at = None
        severity = _normalized_severity(record.get("severity"), *cvss_scores)
        enrichment = AdvisoryEnrichment(source="github", severity=severity,
                                        cvss_scores=tuple(sorted(cvss_scores)), cvss_vectors=tuple(sorted(cvss_vectors)),
                                        epss_scores=tuple(sorted(epss_scores)), vulnerable_functions=tuple(sorted(vulnerable_functions)),
                                        details=str(record.get("description", "")))
        return Advisory(id=canonical, aliases=tuple(sorted(identifiers - {canonical})),
                        severity=severity, withdrawn=withdrawn_at is not None,
                        references=tuple(sorted(valid_references)), modified=updated_at,
                        details=str(record.get("description", "")), source="github", affected_packages=tuple(affected),
                        enrichments=(enrichment,))


class NvdClient:
    """Enrich correlated CVEs from NVD without modifying OSV affected-package evidence."""
    endpoint = "https://services.nvd.nist.gov/rest/json/cves/2.0"

    def __init__(self, http: RetryingHttpClient) -> None:
        """Use the common bounded transport policy for NVD availability evidence."""
        self.http = http

    def enrich(self, advisory: Advisory, *, package: PackageRef | None = None) -> SourceResult[Advisory]:
        """Add NVD CVE metadata while returning the OSV advisory unchanged on NVD failure."""
        cve = next((item for item in (advisory.id, *advisory.aliases) if _CVE.fullmatch(item)), None)
        if not cve:
            return SourceResult(advisory, _status("nvd", SourceState.NOT_APPLICABLE, provenance=self.endpoint))
        fetched = self.lookup(cve)
        if fetched.value is None:
            return SourceResult(advisory, fetched.status)
        return SourceResult(_merge(advisory, fetched.value, package), fetched.status)

    def lookup(self, identifier: str) -> SourceResult[Advisory | None]:
        """Look up one CVE; only an explicit empty vulnerabilities list is a no-match."""
        cve = identifier.strip().upper()
        if not _CVE.fullmatch(cve):
            return SourceResult(None, _status("nvd", SourceState.NOT_APPLICABLE, "invalid CVE identifier", self.endpoint))
        try:
            payload = self.http.request_json("GET", f"{self.endpoint}?{urlencode({'cveId': cve})}")
        except HttpRequestError as error:
            return SourceResult(None, _status("nvd", SourceState.UNAVAILABLE, self.http.last_diagnostic or str(error), self.endpoint))
        if not isinstance(payload, Mapping) or not isinstance(payload.get("vulnerabilities"), list):
            return SourceResult(None, _status("nvd", SourceState.PARTIAL, "NVD response lacks vulnerabilities", self.endpoint))
        if not payload["vulnerabilities"]:
            return SourceResult(None, _status("nvd", SourceState.OK, provenance=self.endpoint))
        entry = payload["vulnerabilities"][0]
        record = entry.get("cve") if isinstance(entry, Mapping) else None
        if not isinstance(record, Mapping) or not isinstance(record.get("id"), str):
            return SourceResult(None, _status("nvd", SourceState.PARTIAL, "NVD vulnerability lacks CVE", self.endpoint))
        if record["id"].strip().upper() != cve:
            return SourceResult(None, _status("nvd", SourceState.PARTIAL,
                                              "NVD response id does not match request", self.endpoint))
        metrics = record.get("metrics", {})
        if not isinstance(metrics, Mapping):
            metrics = {}
            diagnostics = ["NVD metrics are invalid"]
        else:
            diagnostics = []
        severity_values: list[object] = []
        cvss_scores: set[float] = set()
        cvss_vectors: set[str] = set()
        for label, values in metrics.items():
            expected = {"cvssMetricV2": {"2.0"}, "cvssMetricV30": {"3.0"},
                        "cvssMetricV31": {"3.1"}, "cvssMetricV40": {"4.0"}}.get(str(label))
            if expected is None:
                diagnostics.append("NVD CVSS container version is invalid")
                continue
            if not isinstance(values, list):
                diagnostics.append("NVD metric list is invalid")
                continue
            for metric in values:
                data = metric.get("cvssData") if isinstance(metric, Mapping) else None
                if not isinstance(metric, Mapping) or not isinstance(data, Mapping):
                    diagnostics.append("NVD CVSS metric is invalid")
                    continue
                score, vector = data.get("baseScore"), data.get("vectorString")
                try:
                    verified_score, verified_vector = _verified_cvss(score, vector, expected)
                except (KeyError, ValueError):
                    diagnostics.append("NVD CVSS data is invalid")
                    continue
                for severity_value in (data.get("baseSeverity"), metric.get("baseSeverity")):
                    if severity_value is not None and not isinstance(severity_value, str):
                        diagnostics.append("NVD CVSS severity is invalid")
                    else:
                        severity_values.append(severity_value)
                cvss_scores.add(verified_score)
                cvss_vectors.add(verified_vector)
        references = record.get("references", [])
        if not isinstance(references, list):
            diagnostics.append("NVD references are invalid")
            references = []
        valid_references: list[str] = []
        for reference in references:
            url = reference.get("url") if isinstance(reference, Mapping) else None
            if not _is_http_url(url):
                diagnostics.append("NVD reference URL is invalid")
            else:
                valid_references.append(url)
        ids = _identifiers(record, (cve,))
        canonical = cve
        descriptions = record.get("descriptions", [])
        if not isinstance(descriptions, list) or not all(isinstance(item, Mapping) and isinstance(item.get("value"), str)
                                                         for item in descriptions):
            diagnostics.append("NVD descriptions are invalid")
            descriptions = []
        context = " ".join(str(item["value"]) for item in descriptions)
        severity = _normalized_severity(*severity_values, *cvss_scores)
        enrichment = AdvisoryEnrichment(source="nvd", severity=severity,
                                        cvss_scores=tuple(sorted(cvss_scores)), cvss_vectors=tuple(sorted(cvss_vectors)),
                                        details=context)
        return SourceResult(Advisory(id=canonical, aliases=tuple(sorted(ids - {canonical})), severity=severity,
                                     references=tuple(sorted(valid_references)),
                                     details=context, source="nvd", enrichments=(enrichment,)),
                            _status("nvd", SourceState.PARTIAL if diagnostics else SourceState.OK,
                                    "; ".join(sorted(set(diagnostics))), self.endpoint))


class KevClient:
    """Fetch the current CISA KEV catalog independently of advisory alias correlation."""
    endpoint = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"

    def __init__(self, http: RetryingHttpClient) -> None:
        """Use the injected bounded transport to make current KEV availability explicit."""
        self.http = http

    def fetch_ids(self) -> SourceResult[frozenset[str]]:
        """Return normalized CVEs; malformed rows produce partial evidence rather than success."""
        try:
            payload = self.http.request_json("GET", self.endpoint)
        except HttpRequestError as error:
            return SourceResult(frozenset(), _status("kev", SourceState.UNAVAILABLE, self.http.last_diagnostic or str(error), self.endpoint))
        if not isinstance(payload, Mapping) or not isinstance(payload.get("vulnerabilities"), list):
            return SourceResult(frozenset(), _status("kev", SourceState.PARTIAL, "KEV catalog lacks vulnerabilities", self.endpoint))
        identifiers: set[str] = set()
        partial = False
        for row in payload["vulnerabilities"]:
            cve = row.get("cveID") if isinstance(row, Mapping) else None
            normalized = self._normalize(cve) if isinstance(cve, str) else ""
            if not normalized:
                partial = True
            else:
                identifiers.add(normalized)
        return SourceResult(frozenset(identifiers), _status("kev", SourceState.PARTIAL if partial else SourceState.OK,
                                                             "invalid KEV row" if partial else "", self.endpoint))

    @staticmethod
    def _normalize(identifier: str) -> str:
        candidate = identifier.strip().upper()
        return candidate if _CVE.fullmatch(candidate) else ""

    def contains(self, identifier: str, ids: frozenset[str]) -> bool:
        """Check one normalized CVE against an already fetched catalog."""
        return self._normalize(identifier) in ids


def correlate_advisories(advisories: Iterable[Advisory], *, package: PackageRef | None = None) -> list[Advisory]:
    """Correlate shared stable identifiers deterministically without name-similarity merging.

    Every OSV record's package-scoped evidence is unioned in an order-independent connected
    component. Flat compatibility fields are retained only for an explicit package or one
    unambiguous existing OSV projection, preventing cross-package range and fix pooling.
    """
    pending = sorted(advisories, key=lambda item: (item.id, item.aliases, item.source))
    groups: list[list[Advisory]] = []
    for advisory in pending:
        ids = {advisory.id, *advisory.aliases}
        matching = [index for index, group in enumerate(groups) if ids & {value for item in group for value in (item.id, *item.aliases)}]
        if not matching:
            groups.append([advisory])
            continue
        target = groups[matching[0]]
        target.append(advisory)
        for index in reversed(matching[1:]):
            target.extend(groups.pop(index))
    result: list[Advisory] = []
    for group in groups:
        ordered = sorted(group, key=lambda item: (item.id, item.aliases, item.source))
        ids = sorted({value for item in ordered for value in (item.id, *item.aliases)})
        primary = [item for item in ordered if "osv" in item.source.split(";")]
        primary_ids = sorted(item.id for item in primary if not _GHSA.fullmatch(item.id) and not _CVE.fullmatch(item.id))
        canonical = primary_ids[0] if primary_ids else (sorted(item.id for item in primary)[0] if primary else next(
            (item for item in ids if item.startswith("GHSA-")), ids[0])
        )
        evidence = primary or ordered
        affected = tuple(sorted({package for item in evidence for package in item.affected_packages},
                                key=lambda item: (item.ecosystem.casefold(), item.name.casefold(),
                                                  item.ecosystem, item.name, item.purl or "")))
        if package is not None:
            projections = [_project(item, package) for item in primary]
            fixed_versions = tuple(sorted({fix for item in projections for fix in item.fixed_versions}))
            affected_ranges = tuple(sorted({event for item in projections for event in item.affected_ranges}))
        else:
            projections = [item for item in primary if item.fixed_versions or item.affected_ranges]
            if len(projections) == 1 and _projection_identity(projections[0]) is not None:
                fixed_versions, affected_ranges = projections[0].fixed_versions, projections[0].affected_ranges
            else:
                fixed_versions, affected_ranges = (), ()
        result.append(Advisory(id=canonical, aliases=tuple(ids), severity=_normalized_severity(*(item.severity for item in ordered)),
                               withdrawn=any(item.withdrawn for item in ordered),
                               fixed_versions=fixed_versions, affected_ranges=affected_ranges,
                               references=tuple(sorted({reference for item in ordered for reference in item.references})),
                               modified=max((item.modified for item in ordered if item.modified), default=None),
                               details=next((item.details for item in ordered if item.id == canonical and item.details), ""),
                               source=";".join(sorted({source for item in ordered for source in item.source.split(";") if source})),
                               affected_packages=affected,
                               enrichments=tuple(sorted({enrichment for item in ordered for enrichment in item.enrichments},
                                                        key=lambda item: item.source))))
    return sorted(result, key=lambda item: item.id)
