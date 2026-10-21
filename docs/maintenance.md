# Maintain the solution

Deployers can start with the [setup guide](deployment.md). This page covers source checks, packaging and bringing saved Dev changes back into the repository.

## Run the checks

Use Python 3.11 or later and PowerShell 7:

```powershell
python -m pip install -e .
python scripts/run_checks.py --output artifacts/local-verification
```

The command runs the Python checks, PowerShell safeguards and fictional scenarios. Open the generated `artifacts/local-verification/index.html` for results. Generated reports are ignored by Git.

To check the deployment SDK contract without connecting to a tenant:

```powershell
python -m pip install -r scripts/requirements-deployment.txt
python scripts/check_sdk_contract.py
```

The fictional files in `tests/fixtures/` also supply optional Dev sample data. Keep them when maintaining deployment. `scripts/generate_fixtures.py` regenerates those examples; it is not part of installation.

## Build a package

`solution/src/` contains the native solution definitions. Preserve its component IDs, dependencies and Flow tool binding. Edit components in the native designers, then export and review saved changes.

**Build native solution** in GitHub Actions packs reviewed source and uploads a ZIP, checksum and `solution/provenance.json`. That build record contains the source digest and package-specific check status. Building does not contact a tenant or deploy.

For a local build with a configured target and PAC:

```powershell
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Pack -ConfigPath .local/target.json
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Check -ConfigPath .local/target.json `
  -PackagePath artifacts/ZavaMedicalClaimsConcierge.zip
```

Packing rejects source changed since its portability review. A maintainer must inspect a changed export before running `Confirm-NativePortability.ps1`; recording a digest alone is not a review.

## Bring saved Dev changes into source

After configuring the [deployment identity and claims-dev environment](deployment.md#3-build-and-deploy-with-github-actions), run **Propose saved Dev changes**. It exports only this named solution, prepares a portable copy, rebuilds it, runs local checks and proposes a pull request when source changed.

Preparation removes installation values and connection instances, keeps dependencies and sets both packaged flows Off. It does not change running Dev. Raw exports and backups stay ignored. Review definitions, parameter defaults, bindings and checks before merging. A bot-created PR may require an explicit validation run.

The local equivalent is:

```powershell
pwsh scripts/Export-ClaimsDevForReview.ps1 -ConfigPath .local/target.json
```

Merge updates repository source; deployment remains a separate manual action. Business records, sign-ins, permissions and publication are not synchronized by Git.
