# API reference

```{eval-rst}
.. module:: dynamic_metadata
```

## Loader

The driver consumed by build backends.

```{eval-rst}
.. automodule:: dynamic_metadata.loader
   :members:
   :undoc-members:
```

### Plugin protocols

The protocols a provider may implement. Every provider satisfies
`DynamicMetadataProtocol`; the others add optional hooks.

```{eval-rst}
.. autoclass:: dynamic_metadata.protocols.DynamicMetadataProtocol
   :members:
.. autoclass:: dynamic_metadata.protocols.DynamicMetadataBuildStateProtocol
   :members:
.. autoclass:: dynamic_metadata.protocols.DynamicMetadataRequirementsProtocol
   :members:
.. autoclass:: dynamic_metadata.protocols.DynamicMetadataWheelProtocol
   :members:
```

## Field taxonomy

The single source of truth for which `[project]` fields can be dynamic and what
shape their value has.

```{eval-rst}
.. automodule:: dynamic_metadata.info
   :members:
   :undoc-members:
```

## Plugin helpers

Shared helpers that bundled and third-party plugins can reuse.

```{eval-rst}
.. automodule:: dynamic_metadata.plugins
   :members:
   :undoc-members:
```

## Schema

```{eval-rst}
.. automodule:: dynamic_metadata.schema
   :members:
   :undoc-members:
```
