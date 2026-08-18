"""DevOps API gateway (BFF) package.

Declaring this package explicitly (rather than relying on an implicit namespace
package) is required for correct import resolution: a *regular* package found
anywhere on ``sys.path`` always takes precedence over a namespace-package
portion, regardless of path order. Without this file an unrelated third-party
distribution that also ships a top-level ``gateway`` package would shadow this
one and break ``import gateway.app``.
"""

__all__: list[str] = []
