"""
What a job will cost and how long it'll take, at batch prices and now
(decision 081).

Every "now, at full price" box and Accelerate button used to say nothing
of either. Both come from this machine's own record: the cost log, by job
(Claude's part halves at batch prices, the voice and pictures don't),
and the job history, by kind and by whether it ran at batch prices. With
no record yet for a kind, a rough default stands in, and the page says
"about".

A job's kind is what decides both: a short, a long quiz, or a
documentary's stage.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

from core import costs

# Rough defaults before anything of a kind has been made: (dollars at full
# price, of which Claude, minutes now, minutes at batch prices).
DEFAULTS = {
    "short": (0.25, 0.12, 6, 30),
    "longform": (0.20, 0.06, 12, 25),
    "production:outline": (0.03, 0.03, 1, 8),
    "production:script": (0.15, 0.15, 3, 45),
    "production:stills": (2.00, 0.10, 15, 20),
    "production:video": (0.35, 0.02, 20, 22),
    "production:teasers": (0.60, 0.05, 10, 25),
}
FALLBACK = (0.25, 0.12, 6, 30)
RECENT = 20                 # jobs of a kind looked at


def kind_of(seed: dict) -> str:
    seed = seed or {}
    if seed.get("type") == "production":
        stage = seed.get("stage", "")
        # Teasers' second job (approving their scripts) draws and makes them.
        return f"production:{stage}"
    if seed.get("type") == "longform":
        return "longform"
    if seed.get("type") == "animation_preview":
        return "preview"
    return "short"


@dataclass
class Estimate:
    kind: str
    usd_now: float
    usd_batch: float
    minutes_now: float
    minutes_batch: float
    measured: bool          # from this machine's record, or a default

    @property
    def saving(self) -> float:
        return max(0.0, self.usd_now - self.usd_batch)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "usd_now": round(self.usd_now, 2), "usd_batch": round(self.usd_batch, 2),
                "minutes_now": round(self.minutes_now), "minutes_batch": round(self.minutes_batch),
                "measured": self.measured}


def _job_costs(records: list) -> dict:
    """{job id: (dollars at full price, of which Claude)} from the cost log."""
    out = {}
    for r in records:
        job = r.get("job_id")
        if not job:
            continue
        usd = float(r.get("cost_usd") or 0)
        claude = r.get("service") == "claude"
        full = usd * 2 if claude and r.get("batch") else usd
        total, of_claude = out.get(job, (0.0, 0.0))
        out[job] = (total + full, of_claude + (full if claude else 0.0))
    return out


def estimate(seed: dict, channel_key: str = None, history: list = None, records: list = None) -> Estimate:
    """What a job like `seed` costs and takes, now and at batch prices."""
    from core import jobs
    kind = kind_of(seed)
    usd, claude, now_min, batch_min = DEFAULTS.get(kind, FALLBACK)
    history = jobs.history() if history is None else history
    done = [j for j in history if j.get("status") == "done" and kind_of(j.get("seed")) == kind
            and j.get("started_at") is not None and j.get("finished_at") is not None]
    mine = [j for j in done if j.get("channel_key") == channel_key] or done
    mine = sorted(mine, key=lambda j: j["finished_at"])[-RECENT:]
    measured = False
    spent = _job_costs(costs.read_records() if records is None else records)
    paid = [spent[j["id"]] for j in mine if j["id"] in spent and spent[j["id"]][0] > 0]
    if paid:
        usd = statistics.median(p[0] for p in paid)
        claude = statistics.median(p[1] for p in paid)
        measured = True
    direct = [(j["finished_at"] - j["started_at"]) / 60 for j in mine if not j.get("ahead")]
    batched = [(j["finished_at"] - j["started_at"]) / 60 for j in mine if j.get("ahead")]
    if direct:
        now_min, measured = statistics.median(direct), True
    if batched:
        batch_min, measured = statistics.median(batched), True
    batch_min = max(batch_min, now_min)
    return Estimate(kind, usd, usd - claude / 2, now_min, batch_min, measured)


def wait_minutes(active: list = None) -> float:
    """How long until a job queued now would start: whatever is running
    and queued ahead of it (core.job_eta)."""
    from core import job_eta, jobs
    active = jobs.active_in_order() if active is None else active
    if not active:
        return 0.0
    annotated = job_eta.annotate(active, jobs.history())
    return max((j.get("eta_seconds") or 0) for j in annotated) / 60


def finish_label(minutes: float, start_in: float = 0.0, now: float = None) -> str:
    """"~25 min" for soon, "~14:40" for later today, "~Fri 09:10" beyond."""
    total = minutes + start_in
    if total < 50:
        return f"~{max(1, round(total))} min"
    at = (now or time.time()) + total * 60
    same_day = time.strftime("%Y%m%d", time.localtime(at)) == time.strftime("%Y%m%d", time.localtime(now or time.time()))
    return "~" + time.strftime("%H:%M" if same_day else "%a %H:%M", time.localtime(at))


def describe(seed: dict, channel_key: str = None, extra_usd: float = 0.0, extra_usd_now: float = None) -> dict:
    """For a page: both prices (with any known extra, like voice) and when
    each would be done, counting the queue."""
    e = estimate(seed, channel_key)
    wait = wait_minutes()
    now_usd = e.usd_now + (extra_usd if extra_usd_now is None else extra_usd_now)
    batch_usd = e.usd_batch + extra_usd
    return {"usd_now": now_usd, "usd_batch": batch_usd, "extra_now": max(0.0, now_usd - batch_usd),
            "done_now": finish_label(e.minutes_now, wait), "done_batch": finish_label(e.minutes_batch, wait),
            "queue_minutes": round(wait), "measured": e.measured}
