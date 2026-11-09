import shutil

CLI_DIR = EXPORTS / "cli"
shutil.rmtree(CLI_DIR, ignore_errors=True)  # list only what this run writes
kit.write_bundle(kit.restrict(reference_bundle, LEVELS), CLI_DIR / "reference.zip")
kit.write_bundle(kit.restrict(bundle, LEVELS), CLI_DIR / "candidate.zip")
kit.policies(reference_bundle, bundle, LEVELS).write(CLI_DIR)
print(sorted(path.name for path in CLI_DIR.iterdir()))
print((CLI_DIR / "comparison-policy.json").read_text()[:240], "...")
