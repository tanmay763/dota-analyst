"""Live Stratz queries without bulk data entering the model's context (ADR 0001).

Copied from ../dota/src/dota/web/stratz/live.py (its ADR 0009) and adapted for many users:
each call carries the user's own Stratz token (ADR 0002), throttling is per token, and the
dataset cache is namespaced per user in the store (ADR 0004).

- look the schema up (`schema_search`, `schema_type`) and check the `cookbook` first;
- `fetch` runs a read-only query, caches the response by query hash, and returns only its
  shape: one table per list of objects, with row counts, columns and 5 sample rows;
- `aggregate` runs SQL over one or more fetched datasets in DuckDB and returns at most
  ROW_CAP rows.

GraphQL errors go straight back to the model so it can fix its query; only transient HTTP
failures are retried.
"""

import difflib
import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from dota_analyst_mcp.store import Store

STRATZ_URL = "https://api.stratz.com/graphql"
REFERENCES = Path(
    os.getenv(
        "DOTA_ANALYST_REFERENCES",
        Path(__file__).resolve().parents[2]
        / ".claude/skills/stratz-analysis/references",
    )
)
SCHEMA = REFERENCES / "stratz_schema.graphql"
SCHEMA_INDEX = REFERENCES / "schema-index.txt"
COOKBOOK = REFERENCES / "cookbook.md"

CACHE_TTL_SECONDS = 7 * 24 * 3600
ROW_CAP = 100
SAMPLE_ROWS = 5
SAMPLE_CHARS = 60
MIN_INTERVAL_SECONDS = 0.35  # well under Stratz's 20 req/s and 250 req/min per token
MAX_ATTEMPTS = 3
ERROR_BODY_CHARS = 500


class StratzToolError(Exception):
    """A problem the model should read and act on: fix the query, fetch first, and so on."""


def user_namespace(token: str) -> str:
    """A user's cache namespace: a hash of their Stratz token, never the token itself."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def describe_failure(response: httpx.Response) -> str:
    """Name the likely cause of a rejected Stratz call (from ../dota/src/dota/core/queries.py).

    A 403 from Stratz has two very different meanings and the status line alone cannot
    tell them apart, so classify on the response body.
    """
    body = response.text[:ERROR_BODY_CHARS].replace("\n", " ").strip()
    lowered = body.lower()
    if "just a moment" in lowered or "cf-chl" in lowered or "cf_chl" in lowered:
        cause = "Cloudflare challenged the server's IP (not an auth failure; the token was never checked)"
    elif "bearer token is required" in lowered:
        cause = "Stratz rejected the token (reconnect the plugin with a valid Stratz API token)"
    else:
        cause = "unrecognised rejection"
    return f"{cause} | status={response.status_code} cf-ray={response.headers.get('cf-ray', '-')}"


# --- read-only guard --------------------------------------------------------------------

_STRINGS_AND_COMMENTS = re.compile(r'"""(?:.|\n)*?"""|"(?:\\.|[^"\\])*"|#[^\n]*')


def check_read_only(query: str) -> None:
    """Allow only query operations (and fragments); refuse mutations and subscriptions."""
    if not isinstance(query, str) or not query.strip():
        raise StratzToolError("The query is empty.")
    text = _STRINGS_AND_COMMENTS.sub(" ", query)
    depth, head = 0, []
    for ch in text:
        if ch == "{":
            if depth == 0:
                keyword = "".join(head).split("(")[0].split()
                kind = keyword[0] if keyword else "query"  # a bare { ... } is a query
                if kind not in ("query", "fragment"):
                    raise StratzToolError(
                        f"Only read-only queries are allowed; found a {kind!r} operation."
                    )
                head = []
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            head.append(ch)


# --- cache ------------------------------------------------------------------------------


def cache_key(query: str, variables: dict | None) -> str:
    """Stable across reformatting: whitespace runs collapse, and none survives next to
    GraphQL punctuation, so the model rewrapping a query still hits the cache."""
    text = re.sub(r"\s*([{}()\[\]:,!=$@])\s*", r"\1", " ".join(query.split()))
    canonical = json.dumps({"q": text, "v": variables or {}}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


# --- flattening -------------------------------------------------------------------------


def _flatten_record(record: dict, prefix: str, row: dict, children: list) -> None:
    for key, value in record.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            _flatten_record(value, name, row, children)
        elif (
            isinstance(value, list)
            and value
            and all(isinstance(v, dict) for v in value)
        ):
            children.append((name, value))
        elif isinstance(value, list):
            row[name] = json.dumps(value)
        else:
            row[name] = value


def _add_table(tables: dict, path: str, items: list, parents: list | None) -> None:
    import pandas as pd

    rows, children = [], {}
    for i, item in enumerate(items):
        row = {} if parents is None else {"_parent": parents[i]}
        nested: list = []
        _flatten_record(item, "", row, nested)
        rows.append(row)
        for name, values in nested:
            child = children.setdefault(f"{path}.{name}", ([], []))
            child[0].extend(values)
            child[1].extend([i] * len(values))
    tables[path] = pd.DataFrame(rows)
    for child_path, (values, parent_rows) in children.items():
        _add_table(tables, child_path, values, parent_rows)


def flatten(data: dict) -> dict:
    """One table per list of objects (children keep `_parent`, the parent's row);
    scalars outside any list go in a one-row `root` table."""
    import pandas as pd

    tables: dict = {}
    root: dict = {}
    children: list = []
    _flatten_record(data, "", root, children)
    if root:
        tables["root"] = pd.DataFrame([root])
    for path, values in children:
        _add_table(tables, path, values, None)
    return tables


def _sql_name(path: str) -> str:
    return re.sub(r"\W", "_", path)


def _sample_value(value):
    if isinstance(value, str) and len(value) > SAMPLE_CHARS:
        return value[:SAMPLE_CHARS] + "…"
    return value


def _summary(dataset: str, data: dict, cached: bool) -> dict:
    tables = []
    for path, frame in flatten(data).items():
        sample = frame.head(SAMPLE_ROWS).astype(object).where(frame.notna(), None)
        tables.append(
            {
                "table": _sql_name(path),
                "path": path,
                "rows": len(frame),
                "columns": list(frame.columns),
                "sample": [
                    {k: _sample_value(v) for k, v in row.items()}
                    for row in sample.to_dict("records")
                ],
            }
        )
    return {"dataset": dataset, "cached": cached, "tables": tables}


def _graphql_errors(response: httpx.Response) -> str | None:
    """The GraphQL `errors` messages in a response, whatever its status, or None."""
    try:
        body = response.json()
    except ValueError:
        return None
    errors = body.get("errors") if isinstance(body, dict) else None
    if not errors or not isinstance(errors, list):
        return None
    return "; ".join(
        e.get("message", str(e)) if isinstance(e, dict) else str(e) for e in errors[:3]
    )


def _json_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


# --- the client -------------------------------------------------------------------------

_ALIAS = re.compile(r"[a-z][a-z0-9_]{0,15}")


class LiveStratz:
    def __init__(
        self,
        store: Store,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        min_interval: float = MIN_INTERVAL_SECONDS,
    ):
        self._store = store
        self._clock = clock
        self._sleep = sleep
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last_request: dict[str, float] = {}

    def _key(self, token: str, dataset: str) -> str:
        return f"cache/{user_namespace(token)}/{dataset}.json"

    def fetch(self, token: str, query: str, variables: dict | None = None) -> dict:
        check_read_only(query)
        dataset = cache_key(query, variables)
        hit = self._store.read(self._key(token, dataset))
        if hit is not None and self._clock() - hit[1] <= CACHE_TTL_SECONDS:
            return _summary(dataset, json.loads(hit[0]), cached=True)
        data = self.post(token, query, variables)
        self._store.write(self._key(token, dataset), json.dumps(data).encode())
        return _summary(dataset, data, cached=False)

    def aggregate(self, token: str, datasets: dict[str, str], sql: str) -> dict:
        """SQL over fetched datasets; `datasets` maps an alias to a dataset handle, and each
        dataset's tables are named `<alias>_<table>`."""
        import duckdb

        if not datasets:
            raise StratzToolError("Name at least one dataset: {alias: dataset}.")
        frames = {}
        for alias, dataset in datasets.items():
            if not _ALIAS.fullmatch(alias or ""):
                raise StratzToolError(
                    f"Alias {alias!r} must be lowercase letters, digits or _, starting with a letter."
                )
            hit = (
                self._store.read(self._key(token, dataset))
                if re.fullmatch(r"[0-9a-f]{12}", dataset or "")
                else None
            )
            if hit is None:
                raise StratzToolError(
                    f"No dataset {dataset!r}: fetch the data first and use the dataset it returns."
                )
            for path, frame in flatten(json.loads(hit[0])).items():
                frames[f"{alias}_{_sql_name(path)}"] = frame
        con = duckdb.connect(":memory:")
        try:
            for name, frame in frames.items():
                con.register(name, frame)
            # Model-written SQL must not reach files or the network.
            con.execute("SET enable_external_access = false")
            con.execute("SET lock_configuration = true")
            try:
                result = con.execute(sql)
                columns = [d[0] for d in result.description]
                rows = result.fetchall()
            except duckdb.Error as exc:
                raise StratzToolError(f"SQL failed: {exc}") from exc
        finally:
            con.close()
        return {
            "columns": columns,
            "rows": [[_json_value(v) for v in row] for row in rows[:ROW_CAP]],
            "row_count": len(rows),
            "truncated": len(rows) > ROW_CAP,
        }

    def _throttle(self, token: str) -> None:
        user = user_namespace(token)
        with self._lock:
            wait = self._min_interval - (
                time.monotonic() - self._last_request.get(user, 0.0)
            )
            if wait > 0:
                self._sleep(wait)
            self._last_request[user] = time.monotonic()

    def post(self, token: str, query: str, variables: dict | None = None) -> dict:
        """One read-only query with the user's token, retrying only transient failures."""
        check_read_only(query)
        payload = {"query": query, "variables": variables or {}}
        headers = {"Authorization": f"Bearer {token}", "User-Agent": "STRATZ_API"}
        last_error = "no attempt made"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._throttle(token)
            try:
                response = httpx.post(
                    STRATZ_URL, headers=headers, json=payload, timeout=60
                )
            except httpx.TransportError as exc:
                last_error = f"Stratz unreachable: {exc}"
            else:
                # Stratz follows GraphQL over HTTP: a query that fails validation (a
                # misspelled field, a bad enum value) comes back as HTTP 400 with an
                # `errors` body, execution errors as 200 with one. Either way the
                # messages go back to the model, which needs them to fix its query.
                errors = _graphql_errors(response)
                if errors and response.status_code < 500:
                    raise StratzToolError(f"Stratz rejected the query: {errors}")
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = f"Stratz answered {response.status_code}"
                elif response.status_code >= 400:
                    raise StratzToolError(
                        f"Stratz refused the request: {describe_failure(response)}"
                    )
                else:
                    body = response.json()
                    if body.get("data") is None:
                        raise StratzToolError("Stratz returned no data for the query.")
                    return body["data"]
            if attempt < MAX_ATTEMPTS:
                self._sleep(2 ** (attempt - 1))
        raise StratzToolError(f"{last_error} (after {MAX_ATTEMPTS} attempts)")


# --- schema and cookbook ----------------------------------------------------------------

_DEFINITION = re.compile(
    r"^(type|input|enum|interface|union|scalar) (\w+)", re.MULTILINE
)
_BLOCK_DOCS = re.compile(r'\s*"""(?:.|\n)*?"""')
_LINE_DOCS = re.compile(r'(?m)^\s*"[^"\n]*"\s*\n')


def schema_type(name: str, docs: bool = False) -> str:
    """One definition block from the schema, never the whole ~65K-token file.

    Without `docs`, Stratz's descriptions are dropped: fields and arguments only, about a
    fifth of the size.
    """
    lines = SCHEMA.read_text().splitlines()
    start = next(
        (
            i
            for i, line in enumerate(lines)
            if (m := _DEFINITION.match(line)) and m[2] == name
        ),
        None,
    )
    if start is None:
        names = [m[2] for m in _DEFINITION.finditer(SCHEMA.read_text())]
        close = difflib.get_close_matches(name, names, n=5)
        raise StratzToolError(
            f"No schema type {name!r}."
            + (f" Did you mean: {', '.join(close)}?" if close else "")
        )
    block = [lines[start]]
    if "{" in lines[start]:  # scalars and unions are one line
        for line in lines[start + 1 :]:
            block.append(line)
            if line == "}":
                break
    text = "\n".join(block)
    if not docs:
        text = _LINE_DOCS.sub("", _BLOCK_DOCS.sub("", text))
    return text


def schema_search(term: str) -> dict:
    """Type names and root query fields containing `term` (case-insensitive)."""
    needle = term.lower()
    types = [
        line.split()[1]
        for line in SCHEMA_INDEX.read_text().splitlines()
        if len(line.split()) > 1 and needle in line.split()[1].lower()
    ]
    root = schema_type("DotaQuery").splitlines()[1:-1]
    fields = sorted(
        {
            m[1]
            for line in root
            if (m := re.match(r"^  (\w+)[(:]", line)) and needle in m[1].lower()
        }
    )
    return {"types": types, "root_fields": fields}


def cookbook(section: str | None = None) -> str | list[str]:
    """Without a section: the section titles. With one: that section's text."""
    text = COOKBOOK.read_text()
    parts = re.split(r"(?m)^(?=## )", text)
    sections = {
        p.splitlines()[0][3:].strip(): p.strip() for p in parts if p.startswith("## ")
    }
    if section is None:
        return list(sections)
    if section not in sections:
        raise StratzToolError(
            f"No cookbook section {section!r}; sections: {list(sections)}"
        )
    return sections[section]
