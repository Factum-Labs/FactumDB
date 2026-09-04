"""Adapter for the innochecksum utility.

innochecksum checks the checksum of every page in a .ibd file, and with -S it
also prints a count of each page type. This adapter runs both and builds an
IntegrityResult.

Two things about this tool are worth knowing before reading the code:

1. When every page is fine it prints nothing at all and exits 0. Silence is
   success, not a parsing failure, so that has to be turned into an explicit
   "valid" result rather than being mistaken for no output.

2. The -S summary lists every page type including the ones with a count of 0.
   Those zeros are kept. An "Undo log page" count of 0 is the reason a previous
   value cannot be recovered from the tablespace, so dropping zeros as noise
   would throw away a real finding.

The tool is only ever run in read-only mode. innochecksum can rewrite checksums
with -w, and that flag must never be used here because it would modify evidence.
"""

import re
import subprocess

from core.domain.models.canonical import IntegrityResult

# Lines in the summary look like "       1\tIndex page" - spaces, the count,
# a tab, then the name.
PAGE_COUNT_LINE = re.compile(r"^\s*(\d+)\t(.+?)\s*$")


class InnochecksumAdapter:
    """Runs innochecksum on a .ibd file and reports its physical condition."""

    def __init__(self, innochecksum_path="innochecksum"):
        self.innochecksum_path = innochecksum_path

    def validate(self, ibd_path):
        """Check one .ibd file and return an IntegrityResult.

        Runs the tool twice: once with no flags to validate the checksums, and
        once with -S to get the page type breakdown. Neither run writes to the
        file.
        """
        check = subprocess.run(
            [self.innochecksum_path, ibd_path], capture_output=True
        )
        summary = subprocess.run(
            [self.innochecksum_path, "-S", ibd_path], capture_output=True
        )
        return self.parse(check, summary)

    @staticmethod
    def parse(check_result, summary_result):
        """Build an IntegrityResult from the two completed runs.

        Kept separate from validate() so it can be tested with saved output
        instead of a real .ibd file.
        """
        summary_text = summary_result.stdout.decode(errors="replace")
        check_text = (
            check_result.stdout.decode(errors="replace")
            + check_result.stderr.decode(errors="replace")
        )

        page_counts = InnochecksumAdapter._parse_page_counts(summary_text)

        # The page counts add up to the total number of pages. This is the same
        # number innochecksum -c reports, so summing avoids a third run of the
        # tool. If the two ever disagreed that would itself be worth looking at.
        total_pages = sum(page_counts.values())

        # Order matters here. A failed validation run is positive evidence that
        # the file is damaged, and that beats not being able to read the page
        # summary. Checking the summary first would report "unknown" for a file
        # innochecksum had already called invalid, which understates a finding.
        # A damaged file also makes -S fail, so total_pages is 0 in that case -
        # we know the file is bad but could not count its pages.
        if check_result.returncode != 0:
            status = "damaged"
            damaged_pages = InnochecksumAdapter._count_failures(check_text)
        elif summary_result.returncode != 0 or not page_counts:
            # Nothing failed outright, but we could not read enough to judge.
            status = "unknown"
            damaged_pages = 0
        else:
            status = "valid"
            damaged_pages = 0

        return IntegrityResult(
            total_pages=total_pages,
            damaged_pages=damaged_pages,
            status=status,
            page_counts=page_counts,
            raw_summary=summary_text,
        )

    @staticmethod
    def _parse_page_counts(summary_text):
        """Pull the page type counts out of the -S output.

        The section starts after the "#PAGE_COUNT" header line and ends at a
        line of equals signs. There is also a line of equals signs directly
        after the header, so the closing one is only recognised once at least
        one count has been read.
        """
        counts = {}
        in_summary = False

        for line in summary_text.splitlines():
            if line.startswith("#PAGE_COUNT"):
                in_summary = True
                continue
            if not in_summary:
                continue
            if line.startswith("==="):
                if counts:
                    break
                continue

            match = PAGE_COUNT_LINE.match(line)
            if match:
                counts[match.group(2)] = int(match.group(1))

        return counts

    @staticmethod
    def _count_failures(check_text):
        """How many pages innochecksum complained about.

        The tool stops at the first bad page by default, so this is usually 1.
        We return at least 1 whenever validation failed, because a non-zero exit
        means something was wrong even if we could not parse the message.
        """
        failures = 0
        for line in check_text.splitlines():
            if "Fail" in line or "fail" in line:
                failures += 1
        return max(failures, 1)
