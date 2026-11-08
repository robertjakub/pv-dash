# Configuration — the set grammar

Every tool's config file speaks the control grammar
(`common/options.py`): every line a `set <name> <value>`, every comment a
`#` comment — a config file is a runnable script that pipes through the
ctl clients unchanged, and the `show config` control command regenerates
it from the running daemon (the secret knobs render as
`set <name> *** SECRET REMOVED ***` — the value never does, and the
parser refuses the placeholder). The knobs are
filed under the hierarchy nodes the wire spells as words (`modbus`,
`metrics`, `caps`, `control`, `audit`, `dump` — the `?` walk and
`show <node>` describe each namespace) and
`scripts/check_options.py` gates the four surfaces (the flags, the env
twins, the NixOS modules, the README tables) against the registry.

{{#include ../../../cache/modbus_cache.conf}}
