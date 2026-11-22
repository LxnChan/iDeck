# Repository instructions

Follow CONTRIBUTING.md and component-specific licenses/instructions.

## Mainline Checkpoints and Commit Subjects

- Before every substantial change, or any change that may affect core functionality, create an annotated checkpoint tag at the current committed revision before editing. Preserve existing uncommitted work separately from that checkpoint.
- Use a descriptive, unique tag name, record the checkpoint in the change report, and push it to the repository so it can be used for recovery. Do not publish a GitHub Release for checkpoint tags.
- Every commit subject must use `<action>(<scope>): <summary>` with a lowercase action and scope and a concise English summary, unless the user explicitly exempts that particular commit. This also applies to documentation, features, build changes, and follow-up fixes.
- Choose the action to match the actual operation, for example `add` for additions, `fix` for bug fixes, `update` for modifications, `remove` for removals, or `refactor` for restructuring. Do not use `fix` for every change.

## Generalize Fault Fixes Across Applications

- For every reported application fault, treat the reporting application as a reproduction case and investigate the underlying root cause and its impact on other applications.
- Prefer fixes in the responsible shared layer (such as runtime behavior, API implementation, loading, graphics, or packaging) so that all applications affected by the same defect can benefit. Do not stop at making only the reporting application work when a general fix is feasible.
- Search for other callers, equivalent code paths, and duplicated assumptions affected by the same root cause, and address them within the fix's scope. Keep changes tied to that defect and respect component-specific contribution restrictions.
- Avoid application-name checks, executable-specific branches, and hardcoded workarounds unless evidence shows the behavior is genuinely application-specific or a shared fix is currently impractical. Explain and document any such exception and its limitations.
- Validate the original reproduction and, where feasible, representative other applications or shared-layer regression cases that exercise the affected behavior. Check that the generalized behavior preserves compatibility for other callers.
- In each fault-fix report, state the root cause, how the fix covers other applications, what was actually validated, and any remaining application-specific limitations. Do not claim all applications are fixed without supporting evidence.

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

### 2. Workflow Run Naming (Required)

- Every newly triggered CI run, whether started by `push` or `workflow_dispatch`, must use a change-specific title in the form `<action>(<scope>): <summary>` (for example, `fix(packaging): preserve bare dyld roots in portable relink inputs`). Choose a lowercase action that matches the actual operation, following the commit subject rule, and a lowercase scope, followed by a concise English summary of the actual change; the example is a format reference, not a fixed title to reuse.
- This requirement applies to the run's display title (`run-name` / `displayTitle`). The workflow's stable `name` may remain `Build iDeck IPA`.
- Before triggering CI, ensure the commit subject and the workflow's `run-name` configuration produce the required title. Manual dispatches must also supply or derive a compliant title. Do not start new runs with generic titles such as `Build iDeck IPA`, `CI`, or `Manual build`.
- After triggering, verify the actual title with `gh run view <run-id> --json displayTitle,url`. When reporting the run to the user, use its actual title as a bold Markdown link to that run, for example: [**fix(packaging): preserve bare dyld roots in portable relink inputs**](https://github.com/LxnChan/iDeck/actions/runs/43566842106).

### 3. Monitoring Workflow Execution

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

### 4. Handling Workflow Failures

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


