"""
Which external services are set up, what they have cost, and where to go
to top them up.

Four API keys, an OAuth client and two stock-footage accounts are what
make this project run, and until now the only way to find out one had
lapsed was a render failing halfway through. There was also no single
place that said what had been spent — `core.costs` records every billable
call, but per video and per channel, which answers "was that video
expensive" and never "is the ElevenLabs account about to run dry".

**What this cannot do.** It cannot tell you a balance. None of these
providers expose one to an ordinary API key, and inventing a number from
what this app happens to have spent would be worse than useless — it
knows nothing about what anything else on the account has spent, or what
was topped up last week. So each service carries a real link to its own
billing page, and the page says plainly that the balance lives there.
What is shown here is what this installation has spent through that
service, which is the part it genuinely knows.
"""

from __future__ import annotations

import os
import time

from core import costs

# 30 days rather than a calendar month: the useful question is "what is
# this costing me lately", which a month boundary answers badly on the
# 2nd of the month.
RECENT_WINDOW_DAYS = 30


class Service:
    """One external dependency.

    `env_var` is None for a service configured some other way (the
    YouTube OAuth client lives in a file). `cost_services` are the
    `core.costs` service names whose spend belongs to this one — a list
    because a provider can be billed under more than one name.
    """

    def __init__(self, key, name, what_for, env_var, dashboard_url,
                 dashboard_label, cost_services=(), free=False, docs_url=None):
        self.key = key
        self.name = name
        self.what_for = what_for
        self.env_var = env_var
        self.dashboard_url = dashboard_url
        self.dashboard_label = dashboard_label
        self.cost_services = tuple(cost_services)
        # True for a service with a free tier and no balance to run down.
        # It still matters whether the key is set — footage search simply
        # stops working without it — but "add funds" is the wrong verb.
        self.free = free
        self.docs_url = docs_url


SERVICES = (
    Service("anthropic", "Anthropic", "Scripts, footage matching, topic plans",
            "ANTHROPIC_API_KEY",
            "https://console.anthropic.com/settings/billing", "Billing",
            cost_services=("claude",),
            docs_url="https://console.anthropic.com/settings/keys"),
    Service("elevenlabs", "ElevenLabs", "Voiceover",
            "ELEVENLABS_API_KEY",
            "https://elevenlabs.io/app/subscription", "Subscription",
            cost_services=("elevenlabs",),
            docs_url="https://elevenlabs.io/app/settings/api-keys"),
    Service("openai", "OpenAI", "Logo and merch artwork",
            "OPENAI_API_KEY",
            "https://platform.openai.com/settings/organization/billing/overview", "Billing",
            cost_services=("openai-image",),
            docs_url="https://platform.openai.com/api-keys"),
    Service("pexels", "Pexels", "Stock footage and background pictures",
            "PEXELS_API_KEY",
            "https://www.pexels.com/api/", "API account", free=True),
    Service("pixabay", "Pixabay", "Stock footage and background pictures",
            "PIXABAY_API_KEY",
            "https://pixabay.com/api/docs/", "API docs", free=True),
    Service("youtube", "YouTube Data API", "Uploading finished videos",
            None,
            "https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas",
            "Quota", free=True),
)


def _configured(service: Service) -> bool:
    if service.env_var:
        return bool(os.environ.get(service.env_var, "").strip())
    if service.key == "youtube":
        from core import youtube
        try:
            return bool(youtube.client_config())
        except Exception:  # noqa: BLE001 - "not configured" is one of the
            # answers this question has, and a damaged credentials file is
            # the same answer from the reader's point of view.
            return False
    return False


def _spend(records: list, service: Service, since: float = None) -> float:
    return sum(
        r.get("cost_usd") or 0.0 for r in records
        if r.get("service") in service.cost_services
        and (since is None or r.get("ts", 0) >= since)
    )


def collect() -> dict:
    """Every service, with what it is for, whether it is set up, and what
    it has cost. One read of the cost log for all of them."""
    records = costs.read_records()
    since = time.time() - RECENT_WINDOW_DAYS * 86400

    rows, total, recent_total = [], 0.0, 0.0
    for service in SERVICES:
        all_time = _spend(records, service)
        recent = _spend(records, service, since)
        total += all_time
        recent_total += recent
        rows.append({
            "key": service.key,
            "name": service.name,
            "what_for": service.what_for,
            "env_var": service.env_var,
            "configured": _configured(service),
            "free": service.free,
            "dashboard_url": service.dashboard_url,
            "dashboard_label": service.dashboard_label,
            "docs_url": service.docs_url,
            # None, not 0, for a service this project never bills through:
            # "$0.00" beside Pexels reads as a measurement when it is
            # really "there is nothing to measure".
            "total_usd": all_time if service.cost_services else None,
            "recent_usd": recent if service.cost_services else None,
        })

    return {
        "services": rows,
        "total_usd": total,
        "recent_usd": recent_total,
        "window_days": RECENT_WINDOW_DAYS,
        "prices_checked": costs.PRICES_CHECKED,
        "missing": [r["name"] for r in rows if not r["configured"]],
    }
