# Repository instructions

Follow CONTRIBUTING.md and component-specific licenses/instructions.

## CI/CD Workflow & Artifact Delivery (`Build iDeck IPA`)

When making code, resource, or build configuration changes to this repository, you must ensure that the GitHub Actions workflow runs to completion and successfully produces the installable IPA artifact.

### 1. Triggering the Workflow to Produce Artifacts

- **Primary Workflow**: `.github/workflows/build-ipa.yml` (`Build iDeck IPA`).
- **Expected Artifact**: `iDeck-fork-<short_sha>` (containing `iDeck-fork-<short_sha>.ipa` and `*.inventory.json`).
- **Automatic Trigger (`push`)**:
  - After completing code or asset modifications, stage, commit, and push the changes to `main` (`git push origin main`).
  - Pushing non-ignored paths to `main` automatically triggers the `Build iDeck IPA` workflow.
  - *Note*: Changes restricted only to `**.md`, `.gitignore`, `docs/**`, or `experiments/**` are ignored by the `push` trigger (`paths-ignore`).
- **Manual Trigger (`workflow_dispatch`)**:
  - If a build needs to be triggered manually (e.g., after workflow/doc-only updates or custom build parameters), run:
    ```bash
    gh workflow run build-ipa.yml
    ```
  - Available dispatch inputs include:
    - `-f configuration=Debug|Release` (default: `Debug`)
    - `-f rebuild_fex=true|false` (set to `true` when FEXCore sources/patches are modified)
    - `-f release_tag=<tag>`, `-f bundle_id=<id>`, `-f build_number=<num>`

### 2. Monitoring Workflow Execution

Do not consider a code modification task finished immediately after `git push` or `gh workflow run`. Always track the triggered workflow run until it finishes and verify that the artifact is generated:

1. **Locate the triggered run**:
   ```bash
   gh run list --workflow=build-ipa.yml -L 5
   ```
2. **Watch execution until completion**:
   ```bash
   gh run watch <run-id> --exit-status
   ```
3. **Confirm artifact upload**:
   ```bash
   gh run view <run-id>
   ```
   Verify that the status is `completed` (`success`) and the `iDeck-fork-<short_sha>` artifact has been uploaded in the `Upload IPA Artifact` step.

### 3. Handling Workflow Failures

If the workflow fails, is cancelled unexpectedly, or fails to upload the artifact, you must automatically troubleshoot and resolve the failure in a closed loop:

1. **Fetch failure logs**:
   Inspect the failed step and error output using GitHub CLI:
   ```bash
   gh run view <run-id> --log-failed
   ```
2. **Analyze the root cause**:
   - **Runner / CI Environment Issues**: Check for retired runner images (e.g., `macos-*` version deprecation), Homebrew tool installation failures (`llvm`, `bison`), or Xcode SDK selection errors in `.github/workflows/build-ipa.yml`.
   - **Companion Asset Staging Failures**: Check if `gh release download` or fallback URLs failed to stage required static libraries (`*.a`), `prefix-template.tar.gz`, or `StikJIT.framework`.
   - **Wine / Native Library Cross-Compilation Errors**: Inspect errors in `build/wineserver/build.sh`, `build/ntdll-unix/compile_patched.sh`, `build/win32u-unix/compile_patched.sh`, or `build/fex-ios/build.sh`.
   - **Xcode Build (`xcodebuild`) Errors**: Check Swift / Objective-C / C++ compiler diagnostics, missing headers (`build/setup-fex-headers.sh`, `build/setup-wine-headers.sh`), Info.plist patching, or linker errors.
   - **IPA Packaging / Upload Errors**: Check `tools/package-ipa.py` output or missing files under `output/`.
3. **Fix, Re-trigger, and Re-verify**:
   - For transient network/runner glitches, re-run the failed job:
     ```bash
     gh run rerun <run-id> --failed
     ```
   - For code, script, or workflow defects, apply the fix locally, commit and push (or run `gh workflow run build-ipa.yml`), and repeat the monitoring loop until the workflow succeeds and produces the final IPA artifact.


