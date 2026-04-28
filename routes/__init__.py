"""Flask Blueprints for the BABA gateway extensions.

Each module exposes a ``make_blueprint(...)`` factory so dependencies
(limiter, helpers, the open-Thrift-client function, the combined Thrift
namespace) are injected explicitly. This avoids a circular import with
``gateway.py`` while keeping the per-section grouping the upstream review
asked for.
"""
