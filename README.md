# aligned-checker

Checks ALIGN airdrop eligibility through the official Aligned community website.

## Clone the repository

```bash
git clone https://github.com/cyberomanov/aligned-checker.git
cd aligned-checker
```

## Input

- `private_keys.txt`: one EVM private key per non-empty line, with or without `0x`.
- `proxy.txt`: one proxy per non-empty line, in the same order as the keys.

Supported proxy forms include `http://user:pass@host:port`,
`socks5://user:pass@host:port` and `host:port:user:pass`.

The checker validates **all** keys and proxies before making its first network
request. A malformed input or mismatched line count terminates the process.
Every wallet session receives a matched browser identity from `curl_cffi`: its
User-Agent, TLS fingerprint, HTTP/2 settings and default browser headers belong
to the same Chrome or Firefox profile.

## Configuration

1. Put one private key per line in `private_keys.txt`.
2. Put the matching proxy on the same line number in `proxy.txt`.
3. Edit `config.py` to configure the number of independent workers, the random
   sleep range between accounts handled by each worker, and the permitted browser
   profiles.

## Run with uv (recommended)

Install `uv` on macOS or Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart the terminal or load the updated shell environment, then run the checker:

```bash
uv run checker.py
```

## Run with Python and pip

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python checker.py
```

Results are printed and saved to `results.csv`. Private keys and proxy values are
never included in output.

The website requires new sessions to accept its Terms before showing eligibility.
The checker performs that required step and skips the optional newsletter signup.

## Donate

`0x81fb0dF0F16ABC3BE334aB619154C9b3736aB9c1` (EVM)

[@thecyberomanovsmoment](https://t.me/thecyberomanovsmoment)
