{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "modbus-fake-inverter";
  version = "0.5.0";

  src = lib.cleanSource ../../../apps/inverter;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 bin/modbus-fake-inverter.py $out/share/modbus-fake-inverter/modbus-fake-inverter.py
    install -Dm755 bin/modbus-fake-cli.py $out/share/modbus-fake-inverter/modbus-fake-cli.py
    install -dm755 $out/share/modbus-fake-inverter/lib
    install -m644 lib/*.py lib/defaults.json lib/options.json $out/share/modbus-fake-inverter/lib/
    install -dm755 $out/share/modbus-fake-inverter/common
    install -m644 ${../../../common}/*.py $out/share/modbus-fake-inverter/common/
    install -dm755 $out/share/modbus-fake-inverter/common/render
    install -m644 ${../../../common}/render/*.py $out/share/modbus-fake-inverter/common/render/
    install -dm755 $out/share/modbus-fake-inverter/common/runtime
    install -m644 ${../../../common}/runtime/*.py $out/share/modbus-fake-inverter/common/runtime/
    install -dm755 $out/share/modbus-fake-inverter/common/settings
    install -m644 ${../../../common}/settings/*.py $out/share/modbus-fake-inverter/common/settings/
    install -dm755 $out/share/modbus-fake-inverter/common/serve
    install -m644 ${../../../common}/serve/*.py $out/share/modbus-fake-inverter/common/serve/
    install -dm755 $out/share/modbus-fake-inverter/common/wire
    install -m644 ${../../../common}/wire/*.py $out/share/modbus-fake-inverter/common/wire/
    install -dm755 $out/share/modbus-fake-inverter/shared/suite
    install -m644 ${../../../shared}/suite/wire.json $out/share/modbus-fake-inverter/shared/suite/
    install -m644 ${../../../shared}/suite/texts.json $out/share/modbus-fake-inverter/shared/suite/
    install -m644 ${../../../shared}/suite/tags.json $out/share/modbus-fake-inverter/shared/suite/
    install -m644 ${../../../shared}/suite/options.json $out/share/modbus-fake-inverter/shared/suite/
    install -dm755 $out/share/modbus-fake-inverter/common/modbus
    install -m644 ${../../../common}/modbus/*.py $out/share/modbus-fake-inverter/common/modbus/
    install -m644 ${../../../shared}/suite/protocol.json $out/share/modbus-fake-inverter/shared/suite/
    install -dm755 $out/share/modbus-fake-inverter/profiles
    install -m644 ${../../../shared/profiles}/*.json $out/share/modbus-fake-inverter/profiles/
    install -dm755 $out/share/modbus-fake-inverter/examples
    install -m644 ${../../../extras/examples}/acl-ip-prefix.json $out/share/modbus-fake-inverter/examples/
    install -Dm644 ${../../../shared}/schema/acl-ip-prefix.schema.json $out/share/modbus-fake-inverter/acl-ip-prefix.schema.json
    install -m644 examples/modbus-fake-inverter.conf $out/share/modbus-fake-inverter/examples/
    install -dm755 $out/share/man/man1
    install -m644 man/*.1 $out/share/man/man1/
    makeWrapper ${lib.getExe python3} $out/bin/modbus-fake-inverter \
      --add-flags "$out/share/modbus-fake-inverter/modbus-fake-inverter.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-fake-cli \
      --add-flags "$out/share/modbus-fake-inverter/modbus-fake-cli.py"

    runHook postInstall
  '';

  passthru = {
    skipTests = true;
    inherit (finalAttrs) version;
  };

  meta = {
    description = "Fake Inverter Simulator: a stdlib-only Modbus TCP demo device [experimental]";
    longDescription = ''
      EXPERIMENTAL, work in progress: a Modbus TCP demo device emulating
      an inverter with a battery and a smart meter (the device layout comes
      from inverter profiles): day curve or static demo values, the
      modbus-cache diagnostics block, an optional line-protocol control
      server (set/show values at runtime) and seeded chaos injection.
      Includes modbus-fake-cli, the CLI client (one-shot, batch, console) for the control server.
      Python standard library only.
    '';
    license = lib.licenses.bsd3;
    mainProgram = "modbus-fake-inverter";
    platforms = lib.platforms.unix;
  };
})
