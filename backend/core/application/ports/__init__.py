"""Repository ports: what the application core needs from storage.

Each port is an interface. The SQLite adapters in `backend/adapters/` implement
them. The application layer depends on these, never on SQLite, so the storage
technology could be swapped without the rest of the system noticing.

Several of these deliberately reuse the method names from
`core/domain/ports.py` - `schema_for`, `records_for`, `events`, `markers`,
`inventory`, `integrity_for`. Those are the Protocols the domain services read
through. Because Python Protocols are structural, a repository that has those
methods can be handed straight to a domain service with nothing in between: the
same object both stores the data and serves it back.
"""
