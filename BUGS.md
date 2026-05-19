# Bug Tracker

Verified issues from codebase analysis. Ordered by actionability.

---

## Bugs

### ~~B1 — Empty `tag_dirname` creates invalid file paths~~
~~**Files**: `src/pyoas/fastapi/scaffold.py:135`, `testscaffold.py:455`, `routerscaffold.py`~~

~~Tags with only special characters (e.g. `"(v2)"`, `"!!!"`) produce an empty string after
`re.sub(r"[^a-z0-9_]", "_", tag.lower()).strip("_")`, silently creating paths like `".py"`.~~

~~**Fix**: add `tag_dirname = tag_dirname or "unnamed"` after the strip.~~

---

### ~~B2 — `load_config` crashes with cryptic `TypeError` on empty YAML~~
~~**File**: `src/pyoas/core/config.py:276`~~

~~`yaml.safe_load()` returns `None` for an empty file. `_parse_config(None)` then hits
`if "spec" not in data` → `TypeError: argument of type 'NoneType' is not iterable`.~~

~~**Fix**: add `if not isinstance(data, dict): raise ValueError("Config file is empty or not valid YAML")` before calling `_parse_config`.~~

---

### ~~B3 — Generic detection misses complex type parameters~~
~~**File**: `src/pyoas/core/analysis.py:17`~~

~~`_GENERIC_TITLE_RE = re.compile(r"^(\w+)\[(\w+)\]$")` only matches single-word type params.
Titles like `Paginated[list[Pet]]` or `Result[Dict[str, Any]]` silently fall through;
no generic base class is generated for them.~~

~~**Fix**: broaden the regex or use a parser to extract the first top-level bracket group.~~

---

## Design Concerns

### D1 — Signature drift detection is regex-based, not AST-based
**File**: `src/pyoas/fastapi/scaffold.py:383` (`_actual_sig_str`)

Extracts method signatures from existing source via regex. Breaks for decorated methods
(decorator on the preceding line causes the match to fail silently) and methods with
user-added type comments. Result: drift goes unreported for those methods.

---

### D2 — `zip()` without length guard across all scaffolders
**Files**: `scaffold.py:93`, `testscaffold.py:373`, `routerscaffold.py`

`zip(operations, raw_operations)` silently truncates if resolved/raw operation counts
diverge for a tag. Should never happen in practice, but the failure mode is silent data loss.

---

### D3 — No rollback on partial plugin failures
**File**: `src/pyoas/models/generator.py:368`

Plugin hooks run per-tag before writing. If a plugin raises mid-loop, some tag files are
already written while others are not. Cache is not updated for incomplete tags, so the next
run re-generates them — but the output directory is inconsistent until then.

---

## Gaps

### G1 — Doctor misses path-level parameter shadowing
**File**: `src/pyoas/core/doctor.py:135`

Shadowing check only inspects `operation.parameters`. OpenAPI path-item-level parameters
(inherited by all operations in that path) are not checked, so some shadowing cases go unreported.

---

### G2 — Hardcoded path param examples ignore spec `example` fields
**File**: `src/pyoas/fastapi/testscaffold.py:37`

`_PATH_PARAM_EXAMPLES` is a static dict keyed by Python type. If the spec declares
`example:` on a path parameter, it is never used in generated test paths.

---

### G3 — No guard for missing `polyfactory` in generated `conftest.py`
**Files**: `src/pyoas/fastapi/testscaffold.py`, conftest template

Generated `conftest.py` imports `ModelFactory` from `polyfactory`. If the user has
`pyoas[fastapi]` but not `polyfactory` installed, generated tests fail at import with
a cryptic `ModuleNotFoundError`. Either add polyfactory as a hard dep or add a clear comment.
