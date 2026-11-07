# Contributors

Thanks to everyone who made the pv-suite what it is:

- **MK** — patches and ideas:
  - the Modbus auth `suite` scheme — the one-round-trip HMAC-SHA256
    proof-of-key handshake in `common/protocol.py`, spoken by the
    scraper, the fake inverter and the cache;
  - the write allow-list that speaks the device profile —
    `write-registers profile` compiled from the profile's `acl` tree,
    the `deye-sg05lp3` gate, the linter/formatter following;
  - the regtest additions pinning it all.

Be thanked. Be very thanked. ((-;
