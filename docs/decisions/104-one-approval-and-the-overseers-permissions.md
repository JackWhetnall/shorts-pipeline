# 104 — One approval for a film's video; the overseer's permissions

**Status:** active.

## One approval

A film's finished video was approved in two separate places:
- **Review** queued it for publishing;
- **the film's own page** marked its video stage approved, which is what
  starts the teasers.

Approving in Review alone left the film unapproved, so its teasers never
came. Approving on the film's page alone never queued the video. The
owner had to find the film's page as well.

Now either place does both:
- `publish_queue.enqueue` calls `production.video_reviewed`. If the video
  is a film's (`production.film_of`), the film's video stage is approved,
  and its history records "approved in Review".
- Taking the video back out of the queue returns the stage to ready, as
  long as no teasers have been made yet.
- Approving the video on the film's page also queues it for the next
  slot, unless it's already out or discarded.

Teasers aren't overseen. Once the video is approved they are made, and
each goes to Review as a short of its own.

## The overseer stopped on a prompt

The overseer's runs at 23:31 on 13 October and 10:17 on 15 October both
stopped at their second overseer command, waiting for a permission
nobody was there to give. The project's `Bash(python -m core.overseer:*)`
rule wasn't being applied. The commands the owner had approved one by one
were saved exactly, as written, to `.claude/settings.local.json`, and
those matched; nothing else did. The wildcard rule is now in both
settings files, in both syntaxes (`:*` and ` *`).

The storyboard for t0003 was reviewed in this session instead. Three
pictures were redrawn: a stray person, people at a table, and mountains
drawn above the water instead of on the seafloor.
