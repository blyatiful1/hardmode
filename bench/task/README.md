# loganalyze

Tiny log analysis toolkit.

## Usage

    ./verify.sh                              # run the test suite
    python3 -m loglib.cli sample.log
    python3 -m loglib.cli sample.log --level ERROR
    python3 -m loglib.cli sample.log --last 2h

Prints one `LEVEL: count` line per level found.
