{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "modbus-fake-inverter";
  version = "0.4.2";

  src = lib.cleanSource ./.;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 bin/modbus-fake-inverter.py $out/share/modbus-fake-inverter/modbus-fake-inverter.py
    install -Dm755 bin/modbus-fake-ctl.py $out/share/modbus-fake-inverter/modbus-fake-ctl.py
    install -Dm755 bin/modbus-fake-cli.py $out/share/modbus-fake-inverter/modbus-fake-cli.py
    install -dm755 $out/share/modbus-fake-inverter/lib
    install -m644 lib/*.py lib/static.json lib/options.json $out/share/modbus-fake-inverter/lib/
    install -dm755 $out/share/modbus-fake-inverter/common
    install -m644 ${../common}/*.py $out/share/modbus-fake-inverter/common/
    install -dm755 $out/share/modbus-fake-inverter/common/modbus
    install -m644 ${../common}/modbus/*.py $out/share/modbus-fake-inverter/common/modbus/
    install -dm755 $out/share/modbus-fake-inverter/profiles
    install -m644 ${../profiles/profiles}/*.json $out/share/modbus-fake-inverter/profiles/
    install -Dm644 examples/acl-ip-prefix.json $out/share/modbus-fake-inverter/acl-ip-prefix.json
    install -Dm644 schema/acl-ip-prefix.schema.json $out/share/modbus-fake-inverter/acl-ip-prefix.schema.json
    install -dm755 $out/share/man/man1
    install -m644 man/*.1 $out/share/man/man1/
    makeWrapper ${lib.getExe python3} $out/bin/modbus-fake-inverter \
      --add-flags "$out/share/modbus-fake-inverter/modbus-fake-inverter.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-fake-ctl \
      --add-flags "$out/share/modbus-fake-inverter/modbus-fake-ctl.py"
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
      Includes modbus-fake-ctl and modbus-fake-cli, CLI clients for the control server.
      Python standard library only.
    '';
    license = lib.licenses.bsd3;
    mainProgram = "modbus-fake-inverter";
    platforms = lib.platforms.unix;
  };
})
