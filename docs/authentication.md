# Local examiner accounts

The desktop app starts at sign-in. Create an account with a username (3–64 ASCII
letters, numbers, dots, underscores or hyphens), a password of at least 12
characters, and password confirmation. Sign-up succeeds only after the native
device verifier authenticates the currently signed-in OS account. Sign in later
with the FactumDB username and password under that same OS account.

Windows uses Windows Hello through Tauri's native Rust layer and
`IUserConsentVerifierInterop::RequestVerificationForWindowAsync`. The prompt
belongs to the actual FactumDB window. Windows chooses its configured methods,
including PIN, fingerprint or face recognition; FactumDB receives only the
verification result. No OS username or password is requested by FactumDB.
Only `Verified` permits sign-up. Set up Windows Hello in Windows Settings first;
there is no fallback to collecting a Windows password.

After validating sign-up inputs, Python sends a private verification challenge
to Tauri on the inherited sidecar pipes, bound to the current request ID and a
fresh nonce. Tauri performs Windows Hello verification and replies directly to
Python; the frontend cannot submit an approval. The challenge is single-use and
expires when its request finishes. The Python adapter identifies the current
OS user by SID after approval. Standalone backend operation without the native
bridge cannot create Windows accounts. Existing accounts and passwords do not
require migration, and normal FactumDB password sign-in remains unchanged.

Linux uses `pkcheck` with the `org.factumdb.signup` action and the current
process's PID, start time and UID. The supplied policy requires `auth_self`,
without cached authorization. A desktop polkit authentication agent prompts
through its PAM configuration, which may support an account password or an
enrolled fingerprint. Denial, cancellation, timeout, missing policy or missing
agent prevents account creation. System administrators control polkit/PAM;
custom rules can override the packaged policy.
Filesystem permissions still control workspace access, but readable or writable
directories alone do not qualify as fresh device verification.

## Linux setup

Debian and RPM bundles install the policy and declare Python/polkit dependencies.
A running desktop authentication agent is also required. For development or an
AppImage, install the policy once:

```sh
sudo install -m 0644 backend/adapters/security/org.factumdb.signup.policy \
  /usr/share/polkit-1/actions/org.factumdb.signup.policy
```

Ubuntu WSL can exercise the shared authentication service and Linux process
integration. A default WSL installation often lacks an active desktop login
session and polkit agent, so it cannot validate a successful native prompt or
biometric enrollment. Diagnose without changing the system:

```sh
python3 scripts/check_linux_security.py
cd backend
python3 tests/linux_auth_smoke.py
# On an environment known to lack device authentication:
python3 tests/linux_auth_smoke.py --expect-unavailable
```

## Implementation and data

`core/application/authentication.py` owns validation, password checking, account
creation and the in-memory signed-in session. It depends on account-store and
device-security ports. `adapters/persistence/sqlite_accounts.py` implements the
store; `adapters/security/windows.py` retains OS identity and delegates verification
to the native bridge, while `linux.py` invokes polkit. `src-tauri/src/windows_hello.rs`
owns Windows Hello and `sidecar/native_verification.py` owns the private exchange.
React provides one shared sign-up/sign-in screen for both platforms.

No users table existed in the executable case schema. The new `accounts.sql`
creates `users` and `auth_throttle` in **catalog.db only**, rather than adding
credentials to each case database. Passwords use scrypt (N=32768, r=8, p=3), a
random 16-byte salt and constant-time comparison. The algorithm is recorded per
account. Five failed sign-ins block further attempts for 30 seconds; the throttle
persists across application restarts and is shared across local usernames.
The work factor follows an [OWASP scrypt configuration](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#scrypt).

All desktop case, evidence, analysis, settings and export commands require a
backend session. A renderer-supplied examiner value cannot override the account
identity. Logout clears loaded frontend case data; restart requires sign-in.
Existing cases keep their historical examiner text. Accounts share the existing
workspace catalog; this change does not introduce per-account case ownership.

The existing `cases.examiner` field stores the authenticated username at case
creation. Existing views and exports use that saved name. Opening a case under
another account preserves its historical examiner.

Evidence registration and tool runs also store `actor_id` (the catalog's existing
`users.user_id`, written as text) and `actor_username` from the backend session.
Evidence keeps its original registering user through verification; tool runs keep
their initiating user through completion. The evidence and provenance detail
views and existing case exports include these fields. Older records without
attribution remain unknown rather than being assigned to the current user.

This is a local application access gate. Case files are not encrypted, and OS
administrators or processes with access to the app's data/code remain able to
read or modify them. There is no password-recovery or account-deletion flow yet.

## Verify Windows Hello on a device

Open the rebuilt desktop app, choose **Create an account**, and submit the
FactumDB username, password and confirmation. Complete the Windows-owned prompt
with fingerprint or PIN, using its sign-in options if available. Approval should
return to the app signed in; cancellation must leave the account unregistered.
To test another method, sign out and register a different FactumDB username.
These successful native checks require physical user interaction; automated
tests cover result handling and the private exchange without invoking biometrics.

Native API references: [Windows Hello desktop verification](https://learn.microsoft.com/en-us/windows/win32/api/userconsentverifierinterop/nf-userconsentverifierinterop-iuserconsentverifierinterop-requestverificationforwindowasync),
[pkcheck](https://polkit.pages.freedesktop.org/polkit/pkcheck.1.html),
[polkit policy](https://polkit.pages.freedesktop.org/polkit/polkit.8.html).
