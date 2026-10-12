# AWS integration

Configured on 11 October 2026 using the [official AWS setup instructions](https://raw.githubusercontent.com/aws/agent-toolkit-for-aws/refs/heads/main/setup-instructions/setup.md).

- Selected Region: `ap-southeast-2` (Sydney).
- CLI profile: `factumdb-benchmark`; new AWS experience; Medium guidance.
- Installed AWS CLI 2.37.12 and uv 0.13.0 using official Windows installers.
- Browser login and CLI STS identity verification succeeded.
- Toolkit installation and skill catalog verification succeeded through `us-east-1`. The installer added 23 skills.
- Toolkit-generated AWS MCP entries in Codex, Claude, Cursor and Gemini use `AWS_MCP_PROXY_PROFILES=factumdb-benchmark`. Other configuration entries and generated server arguments were preserved.
- An independent MCP client initialized the generated server, listed its tools and successfully executed `STS.GetCallerIdentity`. Its returned identity matches the CLI profile.
- `AGENTS.md` preserves the selected preferences and includes the official new-experience rules in a single marked block.

**Acceptance completed:** the restarted Codex session used the official AWS MCP server for `STS.GetCallerIdentity` in Sydney on 11 October 2026. The identity matched the verified CLI profile. A Free Tier plan-state read also passed and confirmed the active Free plan and USD 100 balance.

The toolkit and global Free Tier endpoints use `us-east-1`; benchmark resources must remain in Sydney. No test machines or supporting infrastructure were provisioned during integration, and no plan upgrade was made.

## Repeat verification

Open a fresh PowerShell so installed command paths are available. When login renewal is needed, use browser authentication; do not enter credentials into chat.

```powershell
aws configure get region --profile factumdb-benchmark
aws sts get-caller-identity --profile factumdb-benchmark
# If the session has expired:
aws login --region ap-southeast-2 --profile factumdb-benchmark
aws agent-toolkit list-available-skills --region us-east-1 --profile factumdb-benchmark
py -3.11 scripts/verify_aws_capabilities.py
py -3.11 scripts/verify_aws_mcp.py
```

The capability audit uses read APIs and EC2 launch dry-runs only. Results are saved to `dist/aws-verification/report.md` and `capabilities.json`. The MCP checker closes its subprocess after each test. `scripts/configure_aws_mcp_profile.py` can reapply the profile after a toolkit reinstall; it preserves all other server settings.

The verified Free-plan balance is **USD 100**, with plan expiration **11 April 2027**. This is the actual API result, despite the earlier expectation of USD 200. Confirm any additional promotional credit or separate expiration dates in AWS Settings → Billing. Eligibility means the service/type is allowed on this plan; metered use can consume credits.

See [the updated benchmark plan](aws-benchmark-plan.md) before provisioning.

The local harness, controller and launch instructions are now prepared in [AWS testing](aws-testing.md). They do not schedule a launch.
