"""
Digest authentication support
"""

import hashlib
from typing import Callable
from urllib.request import parse_http_list

from .base import ClientAuth

DIGEST_METHODS = {
    "MD5": hashlib.md5,
    "SHA": hashlib.sha1,
    "SHA-256": hashlib.sha256,
    "SHA-512": hashlib.sha512,
}


def parse_digest_header(header: str) -> dict:
    """
    Given a www-authenticate or authorization header,
    parse returned fields as a dict.
    """
    fields = {}
    fields_ = parse_http_list(header)
    for field in fields_:
        k, v = field.split("=", 1)
        v = v.strip()
        if v and v[0] == v[-1] == '"':
            v = v[1:-1]
        fields[k.strip().lower()] = v
    return fields


def get_digest_function(algorithm: str) -> Callable[[str], str]:
    """
    Select the right digest function
    """
    assert algorithm in DIGEST_METHODS, f"algorithm {algorithm} not found"
    hashlib_digest = DIGEST_METHODS[algorithm]
    return lambda x: hashlib_digest(x.encode("utf-8")).hexdigest()


class DigestClientAuth(ClientAuth):
    """
    Implementation of Digest algorithm
    """

    def __init__(self, username, password, max_retry=1):
        super().__init__(max_retry)
        self.username = username
        self.password = password

        self.info = None

    def _prepare_digest_header(self, method: str, url: str) -> dict:
        """
        Prepare response header and return a dict; meant for ease of testing
        """

        assert self.info

        algorithm = self.info.get("algorithm", "MD5").upper()
        realm = self.info.get("realm")
        nonce = self.info.get("nonce")
        opaque = self.info.get("opaque")

        hash_digest = get_digest_function(algorithm)

        A1 = "%s:%s:%s" % (self.username, realm, self.password)
        A2 = "%s:%s" % (method, url)

        HA1 = hash_digest(A1)
        HA2 = hash_digest(A2)

        # Direct response as per RFC 2069 - 2.1.1
        response = hash_digest(f"{HA1}:{nonce}:{HA2}")

        base = {
            "username": self.username,
            "realm": realm,
            "nonce": nonce,
            "uri": url,
            "response": response,
        }

        if opaque:
            base["opaque"] = opaque

        return base

    def _build_digest_header(self, method: str, url: str) -> str:
        base = self._prepare_digest_header(method, url)

        opts = ", ".join(f'{k}="{v}"' for k, v in base.items())

        return f"Digest {opts}"

    def handle_401(self, headers: dict):
        """
        Takes the given response and tries digest-auth, if needed.

        :rtype: requests.Response
        """
        auth_header = headers["www-authenticate"]
        if isinstance(auth_header, list):
            auth_header = next(
                header for header in auth_header if header.startswith("Digest ")
            )
            # @TODO There may be several Digest propositions (MD5, SHA-256, ...)

        assert auth_header, "unable to find a Digest header"
        self.info = parse_digest_header(auth_header[6:])

        return super().handle_401(headers)

    def handle_ok(self, headers: dict):
        """
        A response was successful with this authentication. Reset retry count
        :return:
        """
        if "authentication-info" in headers:
            info = parse_digest_header(headers["authentication-info"])
            if "nextnonce" in info:
                self.info["nonce"] = info["nextnonce"]

        super().handle_ok(headers)

    def make_auth(self, method: str, url: str, headers: dict):
        if self.info:
            headers["Authorization"] = self._build_digest_header(method, url)
