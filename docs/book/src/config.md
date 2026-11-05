# Configuration — the set grammar

Every tool's config file speaks the control grammar
(`common/options.py`): every line a `set <name> <value>`, every comment a
`#` comment — a config file is a runnable script that pipes through the
ctl clients unchanged, and the `show config` control command regenerates
it from the running daemon (the secrets never render). The knobs are
filed under the shared sections (device / serving / control plane /
metrics / audit / limits / persistence / logging) and
`scripts/check_options.py` gates the four surfaces (the flags, the env
twins, the NixOS modules, the README tables) against the registry.

{{#include ../../../cache/modbus_cache.conf}}
