# The common layer's specs

The behavior specs of the shared layer — the machinery one
implementation serves to all four tools
([common/](../../common/README.md) is the module index):

- [MODBUS.md](MODBUS.md) — the Modbus reference: the shared protocol
  tree (the limits, the FC policy, the exception codes, the register
  types), the profiles, the auth schemes, the fake's demo devices and
  the cache's write-through.
- [ACL.md](ACL.md) — the access-control map: the ip-prefix gate
  grammar and where each listener checks it (the Modbus connects, the
  /metrics accepts, the write gates), peer-cred and the token ladder.
- [static-defaults.md](static-defaults.md) — the defaults ladder:
  flag > env > config script > the registry row's `default` — the
  static rung's one home and the gate that keeps it.

The per-tool surfaces live in the tools' own READMEs and MANUALs; the
family-wide ledger ([TODO.md](../TODO.md) — every open item including
the one-product sweep, one file) sits at the docs root.
