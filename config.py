"""Runtime settings for aligned-checker."""

# Number of independent workers processing accounts in parallel.
THREADS = 3

# Every worker sleeps for a random duration in this inclusive range before it
# takes its next account. A worker does not sleep after its final account.
SLEEP_MIN_SECONDS = 10
SLEEP_MAX_SECONDS = 30

# curl_cffi profiles include matching TLS, HTTP/2 and default browser headers.
# Profiles are assigned randomly while avoiding the same profile twice in a row.
BROWSER_PROFILES = (
    "chrome136",
    "chrome142",
    "chrome145",
    "chrome146",
    "firefox144",
    "firefox147",
)
