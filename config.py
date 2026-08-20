"""Runtime settings for aligned-checker."""

# Number of independent workers processing accounts in parallel.
THREADS = 3

# Every worker sleeps for a random duration in this range before it takes its
# next account. A worker does not sleep after its final account.
SLEEP_MIN_BETWEEN_ACCS_SEC = 10
SLEEP_MAX_BETWEEN_ACCS_SEC = 30

# Random pause between user-like actions inside one account: opening the site,
# submitting the signature, accepting Terms, and pressing Skip. Automatic HTTP
# redirects are followed immediately, as they are in a browser.
SLEEP_MIN_BETWEEN_REQS_SEC = 3
SLEEP_MAX_BETWEEN_REQS_SEC = 7

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
