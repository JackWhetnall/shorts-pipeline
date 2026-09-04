# 011 — Sparse, validated channel config

**Status:** active. Supersedes full-entry writes.

## Decision

Channels are validated dataclasses. `config/channels.json` stores only
what differs from the defaults, under a `version` key.

## What this replaces

Nine separate `DEFAULT_*` dictionaries merged onto `**fields` by a
function that checked nothing.

Three concrete problems came out of that:

**No validation.** A channel missing its `voice` surfaced as a
`KeyError` several layers deep inside TTS — minutes into a render that
had already paid for a script. Validation now happens on load and names
both the channel and the field.

**Type coercion at every call site.** A colour stored as a JSON list had
to be hand-converted to a tuple on the way in, because PIL wants a tuple.
That now happens once, in the schema.

**The wipe-on-save trap.** Because settings saves wrote the *complete*
field set, any field the settings form did not have an input for was
overwritten with a blank. So every field the setup wizard could set also
had to be duplicated onto the settings form, or saving settings after a
wizard step silently erased it.

That last one was previously handled by documenting it at length and
remembering. It is now structurally impossible: a sparse write can only
change the fields it actually carries, and the form parser mutates the
loaded channel rather than rebuilding one from scratch. There is an
end-to-end test that saves the settings form and asserts the
wizard-only socials survive.

## Versioning

Version 1 was a bare `{key: entry}` mapping. Version 2 wraps that under
`"channels"` alongside `"version"`. The shape is detected on read and
upgraded on the next write, so there is no migration step and no flag
day — and a future field rename now has somewhere to hook.

## Key order

Key order in the file is display order in the UI, so every read and write
preserves it. This is not cosmetic: an earlier rename implementation used
`raw[new] = raw.pop(old)`, and because a pop-then-insert always
re-appends at the end of a Python dict, every renamed channel silently
jumped to the bottom of the home page.

## Mapping-like access

The nested config objects still support `items()` and `[]`. Templates
iterate `pacing.items()` to render one form field per setting, which is
the right thing for a form that should grow a row whenever a setting is
added. Supporting it costs three methods and keeps the validation.
