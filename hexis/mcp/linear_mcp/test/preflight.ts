// Runs before the tests on every `bun test`: Biome writes and checks, then tsc checks the types.
for (const cmd of [
  [process.execPath, "x", "biome", "check", "--write", "."],
  [process.execPath, "x", "tsc", "--noEmit"],
]) {
  const run = Bun.spawnSync(cmd, { stdout: "inherit", stderr: "inherit" });
  if (run.exitCode !== 0) {
    throw new Error(`${cmd.join(" ")} failed with exit code ${run.exitCode}`);
  }
}
