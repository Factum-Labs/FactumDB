"""One transaction shared by several repositories.

Every repository commits its own writes, which is right when it is called on
its own. But the extraction repository has to save a decoded binlog's events,
markers and warnings as one unit, and three separate commits are not one
unit: if the markers failed, the events would already be saved, and the case
would hold events with no transactions and no sign anything went wrong.

transaction() starts and commits a transaction only when none is open yet.
Inside another transaction() it does nothing, so the outermost block decides
whether everything commits or everything rolls back.
"""

from contextlib import contextmanager


@contextmanager
def transaction(connection):
    if connection.in_transaction:
        # Something further out owns this transaction and will commit or
        # roll it back.
        yield
        return

    # BEGIN is sent straight away so in_transaction is already true for
    # everything called inside this block. Otherwise SQLite only starts the
    # transaction at the first INSERT, and a repository called before that
    # would think it was on its own and commit.
    connection.execute("BEGIN")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    connection.commit()
