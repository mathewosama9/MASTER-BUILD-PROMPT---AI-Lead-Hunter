"""Free email domain check via DNS (MX, falling back to A per RFC 5321).

This only proves the *domain* can receive mail. It never marks an address "verified": that needs a
mailbox-level check (e.g. Hunter). No SMTP probing is done (unreliable and harmful to sender reputation).
"""

import logging

log = logging.getLogger(__name__)


async def domain_accepts_mail(domain: str, cache: dict[str, bool | None]) -> bool | None:
    """True/False when DNS answered, None when the lookup itself failed (timeout, resolver error)."""
    if domain in cache:
        return cache[domain]
    try:
        import dns.asyncresolver
        import dns.exception
        import dns.resolver
    except ImportError:  # pragma: no cover - dnspython is a declared dependency
        cache[domain] = None
        return None
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = 5.0
    result: bool | None
    try:
        answer = await resolver.resolve(domain, "MX")
        # A "null MX" (RFC 7505: preference 0, exchange ".") explicitly declares no mail.
        result = any(str(r.exchange) not in (".", "") for r in answer)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        try:
            await resolver.resolve(domain, "A")
            result = True
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            result = False
        except dns.exception.DNSException:
            result = None
    except dns.exception.DNSException as exc:
        log.info("mx lookup failed", extra={"domain": domain, "error": str(exc)[:120]})
        result = None
    cache[domain] = result
    return result
