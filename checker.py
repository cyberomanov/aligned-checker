#!/usr/bin/env python3
"""Check ALIGN airdrop eligibility for private keys using the official website."""

from __future__ import annotations

import argparse
import csv
import queue
import random
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from curl_cffi import requests
from eth_account import Account
from eth_account.messages import encode_defunct

import config

BASE_URL = "https://community.alignedlayer.com"
MESSAGE_TEMPLATE = """ALIGN Airdrop Check wants you to verify your wallet ownership.

Address: {address}"""
AMOUNT_RE = re.compile(r"\b([\d,]+)\s+ALIGN\b", re.IGNORECASE)
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
ADDRESS_IN_TEXT_RE = re.compile(r"0x[0-9a-fA-F]{40}")


class CheckerError(RuntimeError):
    """Expected checker failure that should terminate the process cleanly."""


@dataclass(frozen=True)
class WalletInput:
    index: int
    private_key: str
    address: str
    proxy: str


@dataclass(frozen=True)
class CheckResult:
    index: int
    address: str
    status: str
    align: int | None
    error: str


@dataclass(frozen=True)
class BrowserIdentity:
    profile: str


def read_nonempty_lines(path: Path) -> list[str]:
    if not path.is_file():
        raise CheckerError(f"Required file not found: {path}")
    lines = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()]
    for line_number, line in enumerate(lines, 1):
        if not line:
            raise CheckerError(f"Empty line in {path.name} at line {line_number}")
    return lines


def normalize_private_key(raw: str, line_number: int) -> tuple[str, str]:
    value = raw[2:] if raw.lower().startswith("0x") else raw
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise CheckerError(
            f"Invalid private key at private_keys.txt line {line_number}: "
            "expected exactly 64 hexadecimal characters, optionally prefixed with 0x"
        )
    normalized = "0x" + value.lower()
    try:
        account = Account.from_key(normalized)
    except (TypeError, ValueError) as exc:
        raise CheckerError(
            f"Invalid secp256k1 private key at private_keys.txt line {line_number}"
        ) from exc
    return normalized, account.address


def normalize_proxy(raw: str, line_number: int) -> str:
    value = raw.strip()
    if not value:
        raise CheckerError(f"Empty proxy at proxy.txt line {line_number}")

    if "://" not in value:
        parts = value.split(":")
        if len(parts) == 4:
            host, port, username, password = parts
            value = (
                f"http://{quote(username, safe='')}:{quote(password, safe='')}"
                f"@{host}:{port}"
            )
        else:
            value = "http://" + value

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https", "socks4", "socks4a", "socks5", "socks5h"}:
        raise CheckerError(f"Unsupported proxy scheme at proxy.txt line {line_number}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise CheckerError(f"Invalid proxy port at proxy.txt line {line_number}") from exc
    if not parsed.hostname or port is None:
        raise CheckerError(f"Invalid proxy at proxy.txt line {line_number}")
    if not (1 <= port <= 65535):
        raise CheckerError(f"Invalid proxy port at proxy.txt line {line_number}")
    return urlunsplit(parsed)


def load_wallets(keys_path: Path, proxies_path: Path) -> list[WalletInput]:
    raw_keys = read_nonempty_lines(keys_path)
    raw_proxies = read_nonempty_lines(proxies_path)
    if not raw_keys:
        raise CheckerError("private_keys.txt contains no private keys")
    if len(raw_keys) != len(raw_proxies):
        raise CheckerError(
            f"Line count mismatch: {len(raw_keys)} private keys but {len(raw_proxies)} proxies"
        )

    # Validate the complete input before any network request is made.
    keys = [normalize_private_key(value, number) for number, value in enumerate(raw_keys, 1)]
    proxies = [normalize_proxy(value, number) for number, value in enumerate(raw_proxies, 1)]
    return [
        WalletInput(index=i, private_key=key, address=address, proxy=proxies[i - 1])
        for i, (key, address) in enumerate(keys, 1)
    ]


def csrf_token(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.select_one('meta[name="csrf-token"]')
    token = tag.get("content", "").strip() if tag else ""
    if not token:
        raise CheckerError("The website did not return a CSRF token")
    return token


def sign_login_message(private_key: str, address: str) -> str:
    message = MESSAGE_TEMPLATE.format(address=address)
    signed = Account.sign_message(encode_defunct(text=message), private_key=private_key)
    return "0x" + bytes(signed.signature).hex()


def validate_runtime_config() -> None:
    if not isinstance(config.THREADS, int) or config.THREADS < 1:
        raise CheckerError("config.THREADS must be an integer greater than zero")
    sleep_ranges = (
        (
            "BETWEEN_ACCS",
            config.SLEEP_MIN_BETWEEN_ACCS_SEC,
            config.SLEEP_MAX_BETWEEN_ACCS_SEC,
        ),
        (
            "BETWEEN_REQS",
            config.SLEEP_MIN_BETWEEN_REQS_SEC,
            config.SLEEP_MAX_BETWEEN_REQS_SEC,
        ),
    )
    for label, minimum, maximum in sleep_ranges:
        if minimum < 0 or maximum < 0:
            raise CheckerError(f"SLEEP_{label} values in config.py cannot be negative")
        if minimum > maximum:
            raise CheckerError(
                f"SLEEP_MIN_{label}_SEC cannot exceed SLEEP_MAX_{label}_SEC"
            )
    if not config.BROWSER_PROFILES:
        raise CheckerError("config.BROWSER_PROFILES cannot be empty")


def generate_browser_identities(count: int) -> list[BrowserIdentity]:
    profiles = list(config.BROWSER_PROFILES)
    identities: list[BrowserIdentity] = []
    previous = ""
    for _ in range(count):
        choices = [profile for profile in profiles if profile != previous] or profiles
        selected = random.SystemRandom().choice(choices)
        identities.append(BrowserIdentity(profile=selected))
        previous = selected
    return identities


def navigation_headers(site: str, *, origin: str | None = None, referer: str | None = None) -> dict[str, str]:
    headers = {
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": site,
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    if origin:
        headers["Origin"] = origin
    if referer:
        headers["Referer"] = referer
    return headers


def sleep_between_requests() -> None:
    delay = random.SystemRandom().uniform(
        config.SLEEP_MIN_BETWEEN_REQS_SEC,
        config.SLEEP_MAX_BETWEEN_REQS_SEC,
    )
    if delay > 0:
        time.sleep(delay)


def parse_result(html: str, expected_address: str) -> tuple[str, int | None]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    if "not eligible" in text.lower():
        return "not_eligible", None

    match = AMOUNT_RE.search(text)
    if not match:
        raise CheckerError("Eligibility page contains neither an ALIGN amount nor 'Not eligible'")
    amount = int(match.group(1).replace(",", ""))

    addresses = ADDRESS_IN_TEXT_RE.findall(text)
    if addresses and expected_address.lower() not in {item.lower() for item in addresses}:
        raise CheckerError("Eligibility response belongs to a different wallet address")
    return "eligible", amount


def check_wallet(
        wallet: WalletInput, timeout: float, identity: BrowserIdentity
) -> CheckResult:
    session = requests.Session(
        impersonate=identity.profile,
        default_headers=True,
        proxy=wallet.proxy,
    )

    try:
        home = session.get(
            f"{BASE_URL}/",
            headers=navigation_headers("none"),
            timeout=timeout,
        )
        home.raise_for_status()
        token = csrf_token(home.text)
        signature = sign_login_message(wallet.private_key, wallet.address)

        sleep_between_requests()
        login = session.post(
            f"{BASE_URL}/auth/wallet",
            data={"_csrf_token": token, "address": wallet.address, "signature": signature},
            headers=navigation_headers(
                "same-origin", origin=BASE_URL, referer=f"{BASE_URL}/"
            ),
            timeout=timeout,
            allow_redirects=True,
        )
        login.raise_for_status()

        current = login
        current_path = urlsplit(current.url).path

        if current_path == "/terms":
            sleep_between_requests()
            current = session.post(
                f"{BASE_URL}/terms/accept",
                data={"_csrf_token": csrf_token(current.text)},
                headers=navigation_headers(
                    "same-origin", origin=BASE_URL, referer=f"{BASE_URL}/terms"
                ),
                timeout=timeout,
                allow_redirects=True,
            )
            current.raise_for_status()
            current_path = urlsplit(current.url).path

        if current_path == "/newsletter":
            sleep_between_requests()
            current = session.post(
                f"{BASE_URL}/search",
                data={"_csrf_token": csrf_token(current.text)},
                headers=navigation_headers(
                    "same-origin", origin=BASE_URL, referer=f"{BASE_URL}/newsletter"
                ),
                timeout=timeout,
                allow_redirects=True,
            )
            current.raise_for_status()
            current_path = urlsplit(current.url).path

        if current_path != "/search":
            raise CheckerError(f"unexpected website redirect: {current_path}")

        result_page = current

        status, amount = parse_result(result_page.text, wallet.address)
        return CheckResult(wallet.index, wallet.address, status, amount, "")
    except (requests.RequestsError, CheckerError) as exc:
        return CheckResult(wallet.index, wallet.address, "error", None, str(exc))
    finally:
        session.close()


def write_results(path: Path, results: list[CheckResult]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["index", "address", "status", "align", "error"])
        for result in results:
            writer.writerow(
                [result.index, result.address, result.status, result.align or "", result.error]
            )


def run_workers(
        wallets: list[WalletInput],
        identities: list[BrowserIdentity],
        timeout: float,
) -> list[CheckResult]:
    jobs: queue.Queue[tuple[WalletInput, BrowserIdentity]] = queue.Queue()
    for job in zip(wallets, identities, strict=True):
        jobs.put(job)

    results: list[CheckResult] = []
    results_lock = threading.Lock()
    print_lock = threading.Lock()
    total = len(wallets)

    def worker(worker_number: int) -> None:
        try:
            wallet, identity = jobs.get_nowait()
        except queue.Empty:
            return

        while True:
            try:
                result = check_wallet(wallet, timeout, identity)
                with results_lock:
                    results.append(result)
                with print_lock:
                    if result.status == "eligible":
                        print(
                            f"[{result.index}/{total}] {result.address}: "
                            f"{result.align:,} ALIGN"
                        )
                    elif result.status == "not_eligible":
                        print(f"[{result.index}/{total}] {result.address}: NOT ELIGIBLE")
                    else:
                        print(
                            f"[{result.index}/{total}] {result.address}: "
                            f"ERROR — {result.error}"
                        )
            finally:
                jobs.task_done()

            try:
                wallet, identity = jobs.get_nowait()
            except queue.Empty:
                return

            delay = random.SystemRandom().uniform(
                config.SLEEP_MIN_BETWEEN_ACCS_SEC,
                config.SLEEP_MAX_BETWEEN_ACCS_SEC,
            )
            with print_lock:
                print(f"[worker {worker_number}] sleeping {delay:.1f}s")
            time.sleep(delay)

    worker_count = min(config.THREADS, total)
    threads = [
        threading.Thread(target=worker, args=(number,), name=f"checker-{number}")
        for number in range(1, worker_count + 1)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return sorted(results, key=lambda result: result.index)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keys", type=Path, default=Path("private_keys.txt"))
    parser.add_argument("--proxies", type=Path, default=Path("proxy.txt"))
    parser.add_argument("--output", type=Path, default=Path("results.csv"))
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_runtime_config()
        wallets = load_wallets(args.keys, args.proxies)
        identities = generate_browser_identities(len(wallets))
    except CheckerError as exc:
        print(f"INPUT ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        f"Validated {len(wallets)} private keys and {len(wallets)} proxies. "
        f"Starting {min(config.THREADS, len(wallets))} workers."
    )
    results = run_workers(wallets, identities, args.timeout)

    write_results(args.output, results)
    errors = sum(result.status == "error" for result in results)
    print(f"Saved {len(results)} results to {args.output} ({errors} errors).")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
