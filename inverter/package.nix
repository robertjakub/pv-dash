{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "modbus-fake-inverter";
  version = "0.2.1";

  src = lib.cleanSource ./.;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 bin/fake_inverter.py $out/share/modbus-fake-inverter/fake_inverter.py
    install -Dm755 bin/fake_ctl.py $out/share/modbus-fake-inverter/fake_ctl.py
    install -Dm755 bin/fake_cli.py $out/share/modbus-fake-inverter/fake_cli.py
    install -dm755 $out/share/modbus-fake-inverter/lib
    install -m644 lib/*.py lib/static.json $out/share/modbus-fake-inverter/lib/
    install -dm755 $out/share/modbus-fake-inverter/profiles
    install -m644 ${../profiles}/*.json $out/share/modbus-fake-inverter/profiles/
    makeWrapper ${lib.getExe python3} $out/bin/modbus-fake-inverter \
      --add-flags "$out/share/modbus-fake-inverter/fake_inverter.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-fake-ctl \
      --add-flags "$out/share/modbus-fake-inverter/fake_ctl.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-fake-cli \
      --add-flags "$out/share/modbus-fake-inverter/fake_cli.py"

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
      Includes fake_ctl and fake_cli, CLI clients for the control server.
      Python standard library only.
    '';
    license = lib.licenses.bsd3;
    mainProgram = "modbus-fake-inverter";
    platforms = lib.platforms.unix;
  };
})
