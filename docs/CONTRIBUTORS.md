# Contributors

Thanks to everyone who made the pv-suite what it is:

- **MK** — patches and ideas:
  - the `waveshare` auth-upstream scheme — the cache presenting the
    shared key as a Waveshare RS485-to-TCP gateway's connection
    password, idea and patches both;
  - the Modbus auth `suite` scheme — the one-round-trip HMAC-SHA256
    proof-of-key handshake in `common/protocol.py`, spoken by the
    scraper, the fake inverter and the cache;
  - the write allow-list that speaks the device profile —
    `write-registers profile` compiled from the profile's `acl` tree,
    the `deye-sg05lp3` gate, the linter/formatter following;
  - the regtest additions pinning it all;
  - the idea behind the docker rework — the per-tool env files and the
    config volume shrinking to the required file artifacts (`81644d5`,
    `3db29d3`, `222e37c`).

Be thanked. Be very thanked. ((-;
