# Commercial edition engineering review

Reviewed 2026-10-11, starting from public commit 6db5892.

## Scope and changes

- Removed audEERING MSP-dim and its copied model-card implementation (CC-BY-NC-SA-4.0).
- Removed emotion2vec and FunASR/ModelScope runtime dependencies. The custom model
  license includes "reference and learning purposes" wording; this release does
  not depend on interpreting that wording as commercial permission.
- Replaced the directly imported GPL-3.0 Parselmouth library with original NumPy
  acoustic measurements. Pitch/intensity are estimates, not emotion predictions.
- Removed unused AST model loader.
- New emotion/arousal/valence fields remain NULL. Existing historical data remain
  readable. Summaries can still describe conversation context from the text.
- Automatic ASR candidates must declare MIT, Apache-2.0 or BSD-3-Clause before
  download/evaluation. Model choice changes still require a release review.

## Licenses and distribution boundary

The public MIT version remains available with its original rights. The original
notice is retained in licenses/Shema-MIT.txt. New modifications are proprietary.
Do not push this working branch to the public repository. The commercial source
must live in a private repository or the owner's local checkout.

See THIRD_PARTY_NOTICES.md for retained components and original sources.
FFmpeg is a separate executable installed by winget, invoked through a process;
it is not linked into Shema or bundled in the commercial archive. GPL does not
prohibit selling software, but bundling FFmpeg requires its own compliance work.
Python wheels/models are downloaded from their publishers and retain their own
license files. Do not bundle these files without collecting the matching licenses
and any required source offers. Gemma 3 is subject to Google's use restrictions;
the installer must obtain acceptance before downloading it.

## Verification boundaries

Automated tests cover acoustic estimates on known signals, silence/noise handling,
retained transcript/database behavior with missing emotion fields, and ASR license
filtering. They do not establish Hebrew transcription accuracy or replace a full
CPU/GPU install and real-audio acceptance run. Third-party model license declarations
are not independent verification of rights in their training data.

## Before live sales

1. Create/approve the merchant's Lemon Squeezy store; enter the real product IDs,
   checkout URL and agreed price. Run a real provider test-mode purchase/activation,
   refund and transfer before enabling live checkout.
2. Keep the new source private. Retain legacy MIT notices. Any contributions whose
   ownership differs remain subject to their original rights.
3. Review the final EULA, business details, refund policy and privacy wording.
4. Build/sign the Windows distribution and Android APK on the release machine;
   smoke-test fresh install, upgrade, offline use and uninstall. Signing/build
   output has not been produced merely by passing unit tests.
5. Host the commercial site outside GitHub Pages.

This is an engineering license inventory and release checklist, not a legal opinion.
