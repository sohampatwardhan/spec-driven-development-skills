# Policy and evidence interpretation

Use this reference when reviewing a report, configuring stricter policy, or supplying reachability
evidence. Policy applies only after exact package applicability is established.

## Finding decision order

The first applicable default rule wins. Project policy may promote a warning to a block but cannot
downgrade a default block or KEV result.

| Condition | Default decision | Rationale |
|---|---|---|
| Advisory is withdrawn | Excluded | Retain provenance, but omit it from active counts. |
| CVE is in current CISA KEV | Block | Scope, reachability, severity, and fix availability do not weaken known exploitation. |
| No authoritative fixed version | Warning | Do not invent safety from a newer release. Release additionally needs mitigation and explicit risk acceptance. |
| Development-only dependency | Warning | A stricter project may block it. |
| Concrete evidence proves unreachable | Warning | Retain and review the exclusion evidence. |
| Non-development high/critical finding with a fix | Block | Applies to runtime or unknown scope when reachable, unknown, or not assessed. |
| Other active severity | Warning | Includes low, medium, and unknown unless promoted. |

## Stricter policy file

Supply `--policy /path/to/policy.json` with only these fields:

```json
{
  "block_warnings": false,
  "block_no_fix": true,
  "block_development": false,
  "block_proven_unreachable": false,
  "block_severities": ["medium"]
}
```

Boolean promotion fields affect their matching warnings. `block_severities` accepts only
`unknown`, `low`, `medium`, `high`, and `critical`. Unknown fields or wrong types make the invocation
invalid rather than silently changing policy.

## Mode and aggregate matrix

| Evidence or decision | Change | Main | Release |
|---|---|---|---|
| Complete inventory and matching baseline | Skip full remote scan | Not used | Not used |
| Incomplete inventory | Explicit warning/source gap; continue scanning | Unavailable | Unavailable |
| OSV, KEV, or applicable native adapter partial/unavailable/stale | Warning; retain known blocks | Unavailable | Unavailable |
| GitHub/NVD enrichment failure | Visible source gap; retain primary findings | Does not erase required-source completion | Does not erase required-source completion |
| Active blocking finding | Blocked unless required evidence is unavailable | Blocked | Blocked |
| No-fix warning without mitigation and acceptance | Warning | Warning | Unavailable |
| Report write failure | Unavailable | Unavailable | Unavailable |

In main and release, required-evidence unavailability takes aggregate precedence over a known block,
but the block remains in the report. In change mode, a source gap prevents a `pass`: the outcome is
`warnings`, or `blocked` when a known blocking finding is also present.

## Reachability evidence

The document must be readable JSON no larger than 1 MiB, use schema major `1`, and contain an
`annotations` object. Keys combine an exact versioned package URL and stable advisory ID.

```json
{
  "schema_version": "1",
  "annotations": {
    "pkg:pypi/example@1.2.3|OSV-2026-1": {
      "status": "unreachable",
      "method": "delivered_artifact_exclusion",
      "evidence": ["evidence/bundle-manifest.json#excluded-components"],
      "producer": "release-bundle-analyzer",
      "timestamp": "2026-08-08T12:00:00Z"
    }
  }
}
```

| State | Accepted methods | Evidence rule |
|---|---|---|
| `reachable` | `direct_call`, `runtime_loading`, `enabled_configuration`, `execution_trace`, `dynamic_analysis` | Require one or more concrete evidence references. |
| `unreachable` | `delivered_artifact_exclusion`, `call_graph_exclusion`, `configuration_exclusion` | Require one or more concrete exclusion references. |
| `unknown` | Any non-empty review method | Record why analysis was inconclusive. |
| `not_assessed` | Any non-empty review method | Record that no assessment was made. |

Each annotation also requires a non-empty producer and timezone-aware timestamp. A key may contain a
list of independent producer records. Valid reachable evidence wins conflicts; other conflicts,
duplicate keys, unsupported methods, missing proof, and malformed supplied files fail closed to
unknown. Absence of an optional reachability file means not assessed.

Return to the [operational workflow](../SKILL.md).
