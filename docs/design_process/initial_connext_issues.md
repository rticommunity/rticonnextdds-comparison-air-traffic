# Initial Issues — Connext DDS Python Implementation

Friction points encountered during AI-assisted generation of a Connext DDS 7.7.0 Python application. These should be captured in the "ask Connext" MCP knowledge base so future designs avoid them.

---

## 1. `idl.bounded_str()` Does Not Exist

**Problem:** Generated code used `idl.bounded_str(16)` as a default value for bounded string fields. This function does not exist in `rti.types`.

**Actual API:** Bounded strings are declared via `member_annotations` using `idl.bound(N)`, not as a default value factory:

```python
# WRONG
@idl.struct
class Waypoint:
    name: str = idl.bounded_str(16)  # AttributeError

# CORRECT
@idl.struct(member_annotations={"name": [idl.bound(16)]})
class Waypoint:
    name: str = ""
```

**Impact:** Runtime `AttributeError` on import of type definitions.

**MCP Fix:** The MCP should document that `rti.types` has `idl.bound(N)` as an annotation (used in `member_annotations` dict), not `idl.bounded_str()`. All bounded strings use `str = ""` as the default with `idl.bound(N)` in the annotations.

---

## 2. `Replier.receive_requests()` Throws TimeoutError on Zero Duration

**Problem:** Calling `replier.receive_requests(dds.Duration(seconds=0))` raises `rti.connextdds.TimeoutError` instead of returning an empty collection when no requests are pending.

**Impact:** Services that poll for requests in a loop crash immediately on first iteration.

**Workaround:** Wrap in `try/except dds.TimeoutError`:

```python
def handle_requests(self):
    try:
        requests = self.replier.receive_requests(dds.Duration(seconds=0))
    except dds.TimeoutError:
        return
    for request, info in requests:
        ...
```

**MCP Fix:** The MCP should always include the `TimeoutError` handling pattern when showing `receive_requests()` or `receive_replies()` with non-blocking (zero) timeouts. This is a common pitfall.

---

## 3. Lifespan QoS on DataReader (Invalid)

**Problem:** The generated QoS XML included `<lifespan>` inside `<datareader_qos>`. Lifespan is a **DataWriter-only** QoS policy — it has no meaning on the reader side and causes XML validation errors.

**Impact:** QoS file flagged as invalid; required manual removal.

**MCP Fix:** When generating QoS profiles, never place `<lifespan>` under `<datareader_qos>`. The MCP should know which QoS policies are writer-only vs reader-only vs both.

---

## 4. `@nested` Annotation on Enums (Invalid IDL)

**Problem:** Initial design applied `@nested` to enum types. The `@nested` annotation only applies to **structs and unions**, not enums. Enums should use `@appendable` for extensibility.

**Impact:** Would cause IDL compilation errors if fed to `rtiddsgen`.

**MCP Fix:** The MCP should enforce that `@nested` is only recommended for struct/union types, never for enums. Enum best practice is `@appendable` only.

---

## 5. Missing `@mutable` on `@topic` Types with Optional Members

**Problem:** Initial design used `@appendable` on `@topic` types that have many `@optional` members. The recommended practice for types with optional members is `@mutable`, which allows adding, removing, and reordering fields.

**Impact:** Reduced evolvability of the data model; `@appendable` only allows appending new fields at the end.

**MCP Fix:** The MCP should recommend `@mutable` as the default for `@topic` types, especially those with `@optional` members. Reserve `@appendable` for nested helper structs and enums where the simpler extensibility model is sufficient.

---

## 6. `sys.path` String Concatenation vs Path Resolution

**Problem:** Generated code used `sys.path.insert(0, f"{__file__}/../../")` to find sibling modules (`atc_types`, `common`). This is string concatenation, not path resolution — it produces paths like `.../flightplan_service.py/../../` which don't resolve.

**Correct pattern:**

```python
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
```

**Impact:** `ModuleNotFoundError` on every application startup.

**MCP Fix:** When generating multi-module Python projects, the MCP should use `os.path.dirname(__file__)` for path resolution, or recommend a `pyproject.toml` / package install approach instead of `sys.path` hacking.

---

## 7. QoS File Path Resolution (Relative Path Depth)

**Problem:** The `common/__init__.py` utility module resolved the QoS XML path as `os.path.join(os.path.dirname(__file__), "..", "qos", "USER_QOS_PROFILES.xml")`. Since `common/` is at `src/common/`, one `..` only reaches `src/`, but the QoS file is at `connext_dds/qos/`. Needed `../..` to get from `src/common/` up to `connext_dds/`.

**Impact:** `rti.connextdds.Error: reload profiles` — DDS could not find the QoS file.

**MCP Fix:** When recommending project structures with separate `src/` and `qos/` directories, the MCP should be explicit about relative path depth from utility modules to configuration files. Better yet, recommend an environment variable or a path computed from the project root.

---

## 8. RTI License File Not in Environment

**Problem:** Running Connext applications without `NDDSHOME` and `RTI_LICENSE_FILE` environment variables produces `[RTI LICENSE ERROR] | RTI Connext No source for License information` and fails to create a DomainParticipant.

**Impact:** Every application crashes on DomainParticipant creation.

**MCP Fix:** When generating run scripts or setup instructions, always include:

```bash
export NDDSHOME=/path/to/rti_connext_dds-7.7.0
export RTI_LICENSE_FILE=$NDDSHOME/rti_license.dat
```

Or remind users to source the Connext environment script:

```bash
source $NDDSHOME/resource/scripts/rtisetenv_<arch>.bash
```

---

## 9. Inconsistent CLI Argument Names Across Apps

**Problem:** The tower app used `--airport` while airport_app and the run script used `--airport-code`. This caused the launch script to fail when invoking the tower.

**Impact:** `run_scenario.sh tower --airport-code KJFK` failed with "unrecognized arguments."

**MCP Fix:** When generating multi-application projects, the MCP should recommend consistent CLI argument names across all apps. Establish a naming convention in the design document (e.g., always `--airport-code` for ICAO codes).

---

## Summary Table

| # | Issue | Category | Severity |
|---|---|---|---|
| 1 | `idl.bounded_str()` doesn't exist | Python API knowledge | High — runtime crash |
| 2 | `receive_requests` TimeoutError | Python API knowledge | High — runtime crash |
| 3 | Lifespan on DataReader | QoS generation | Medium — XML error |
| 4 | `@nested` on enums | IDL annotation rules | Medium — compile error |
| 5 | `@appendable` vs `@mutable` on topics | IDL best practices | Low — design quality |
| 6 | `sys.path` string concat vs resolution | Code generation | High — runtime crash |
| 7 | QoS file relative path depth | Project structure | Medium — runtime crash |
| 8 | Missing license env vars | Setup / deployment | Medium — runtime crash |
| 9 | Inconsistent CLI arg names | Code generation | Low — launch failure |

