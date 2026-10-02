"""Reads mysql-bin.index, the server's own list of its binary logs.

Without it there is no way to know whether the binlogs we were given are all
of them. With it we can say "the server had 6 logs and we were given 5", so a
missing log is reported as an evidence gap instead of going unnoticed.

The file is plain text written by MySQL: one log path per line, oldest first,
for example /var/log/mysql/mysql-bin.000001, or ./mysql-bin.000001 when the
logs live in the data directory. The paths are where the logs were on the
server, not where our working copies are, so only the file names are kept.

No external tool is involved, so there is no tool run to record. The index is
registered evidence with its own hash, and that is what ties an inventory to
the exact file it was read from.
"""

import os


class MysqlBinlogIndexAdapter:
    """Implements the BinlogIndexReader port."""

    def read(self, working_copy_path):
        """The log file names, in the order the index lists them.

        A name listed twice is refused. MySQL never writes one, so it means the
        file was edited or damaged, and the order of the logs - which the
        transaction grouping relies on - can no longer be trusted.
        """
        with open(working_copy_path, encoding="utf-8") as index:
            names = [os.path.basename(line.strip()) for line in index if line.strip()]
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            raise ValueError(
                f"{os.path.basename(working_copy_path)} lists {', '.join(repeated)} "
                "more than once"
            )
        return tuple(names)
