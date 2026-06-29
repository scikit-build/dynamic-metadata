# For backend authors

**You do not need to depend on dynamic-metadata to support plugins.** This library
provides some helper functions you can use if you want, but you can implement them
yourself following the standard provided or vendor the helper file (which will be
tested and supported).

Collect the array of `[[tool.dynamic-metadata]]` entries and process them in
order: load each entry's `provider`, call its `dynamic_metadata` hook with a
snapshot of the project resolved so far, and merge the returned fragment in.
Because the order is explicit, there is no dependency graph to compute.

The reference loop lives in {mod}`dynamic_metadata.loader`. Its entry point is:

```python
def process_dynamic_metadata(
    project: Mapping[str, Any],
    entries: list[dict[str, Any]],
    build_state: str,
) -> dict[str, Any]: ...
```

It builds a plain `dict` and applies entries in order. Each provider gets a
read-only snapshot (a `MappingProxyType`) of the project resolved so far, so a
later entry can read an earlier one's result with `project[...]`; a forward
reference is just a `KeyError`, and cycles are structurally impossible. The
returned fragment is merged per field: lists append, tables add keys (PEP 808
add-only), and a single-value field is replaced if a later entry targets it. Each
resolved field is removed from `dynamic`.

See the [API reference](api/index.md) for the protocols (`DynamicMetadataProtocol`
and its subclasses) and the field taxonomy in {mod}`dynamic_metadata.info` that
the loader validates against.
</content>
