# Running the prepared AWS tests

Prepared on 11 October 2026 for the finished application on **12 October 2026**. Nothing is scheduled and no AWS resources are running. Start the campaign explicitly after the application is ready. Rebuild artifacts after the final changes; today's harness archive is a preparation snapshot.

Execution started on 14 October 2026 against application revision `c03a50be48ab798220db59ab78502667f67243c8`. The updated harness includes PDF test dependencies, packaged fonts/SQL/policies, synthetic scenario metadata and rule documentation. Production engine measurements use the packaged Windows interpreter/backend and the packaged Ubuntu backend. Later guests continue independent engine measurements after a workload failure so lower-memory diagnostics still cover both CPU limits.

Guest artifact transfers now use the narrowly scoped EC2 role. AWS login credentials rotate after about 15 minutes, which can invalidate a signed result-upload URL before a longer test completes. `benchmarks/aws/cleanup.py` can recover full teardown from a recorded campaign after a controller interruption; it verifies project identity and stack ownership before deleting anything.

## What is ready

- `benchmarks/aws/campaign.json`: seven sequential configurations, Ubuntu at 1/2/4/8 GiB and Windows Server at 2/4/8 GiB, two EC2 vCPUs each. Application process affinity compares two CPUs with one.
- `benchmarks/aws/guest.py`: bounded commands, warm-up plus three repetitions, 100 ms memory/CPU/paging samples, stdout/stderr, timeouts and process-tree termination. Source correctness tests and packaged backend smoke checks precede scaled engine runs.
- `benchmarks/aws/workload.py`: deterministic synthetic data at 2,500, 10,000, 40,000 and 100,000 records; grouping, correlation, reconstruction and reconciliation, followed by compact record/graph serialization. Repeated output hashes must match. No personal evidence is packaged.
- `benchmarks/aws/template.py`: one temporary CloudFormation stack per machine, private encrypted artifact bucket, SSM guest service role, no inbound management ports, IMDSv2, encrypted 40 GiB gp3 disk with deletion on termination, a 90-minute guest shutdown timer and a separate Lambda/EventBridge expiry watchdog.
- `benchmarks/aws/controller.py`: refreshes eligibility, prices, plan, identity and capacity checks; probes the watchdog's own termination permission using a dry-run; executes via SSM; downloads guest archives and SSM output; then terminates the instance, empties its bucket and deletes its entire stack. Failed teardown stops the campaign and records remaining resource identifiers.
- `dist/aws-preparation/`: generated template, harness ZIP and hashes, source manifest, budget estimate and local smoke results. `benchmarks/aws/prepare.py` rebuilds these offline.
- `.bundle-cache/aws-controller/`: isolated controller environment with boto3 CRT credential support. `.bundle-cache/aws-validators/`: official SHA-256-verified cfn-guard 3.2.1. cfn-lint 1.57.2 is available through uv's isolated tool cache.

The generated template passed **cfn-lint with zero errors/warnings** and the campaign's **four cfn-guard rules with zero violations**. AWS `CloudFormation.ValidateTemplate` also passed through authenticated MCP. These are schema/security checks, not proof of live provisioning or IAM-role attachment. Creation-time service validation, watchdog permission probe and end-to-end execution remain launch-time checks.

## Budget

The Price List API returned these shared-tenancy On-Demand Sydney hourly rates on 11 October 2026:

| Instance | Linux USD/hour | Standard Windows USD/hour |
|---|---:|---:|
| t3.micro | 0.0132 | 0.0224 |
| t3.small | 0.0264 | 0.0448 |
| c7i-flex.large | 0.11072 | 0.19812 |
| m7i-flex.large | 0.1197 | 0.2071 |

The seven configurations at a maximum 90 minutes each give **USD 1.08006 compute**, plus a conservative **USD 3 allowance** for disks, IPv4, transfers, logs and watchdog services. The initial forecast is **USD 4.08006**, below the **USD 16 scheduling limit**, with a separate **USD 4 cleanup reserve** inside the authorized **USD 20 total**. Ancillary allowance is an estimate; this is not an AWS billing cap. T3 instances use **standard** CPU credits to avoid surplus-credit fees; throttling/credit availability can affect timing. Refresh prices and include setup/cleanup delays before starting.

## Start when the application is finished

Ask Codex to run the prepared campaign with the finished revision, or follow these steps. Do not run the final `--execute` command until both OS artifacts are freshly built.

1. Build Windows using `npm run bundle:windows`; use its current resource directory containing `runtime/windows` and `sources`. The controller stages the source backend that Tauri maps into the installer, or verifies an installed `backend` directory if supplied. Build Ubuntu 24.04 using `npm run bundle:linux` from the documented Ubuntu/WSL build environment. Both guests compare packaged backend source hashes with the test manifest before measuring it, rejecting stale application code.
2. Reverify the named profile's authenticated identity, active Free plan, remaining credits, selected Sydney Region, EC2 quota and supported types through AWS MCP. Login renewal uses the browser. Today's CLI and restarted MCP identities matched, and the active Free-plan balance was USD 100. No upgrade is needed.
3. Regenerate local preparation and run its checks:

```powershell
py -3.11 benchmarks/aws/prepare.py
py -3.11 -m pytest benchmarks/aws/test_preparation.py -q
py -3.11 benchmarks/aws/guest.py --smoke
& "$env:USERPROFILE\.local\bin\uvx.exe" --from cfn-lint==1.57.2 cfn-lint --format json --regions ap-southeast-2 --template dist/aws-preparation/benchmark.template.json
& '.\.bundle-cache\aws-validators\cfn-guard-v3-x86_64-windows-latest\cfn-guard.exe' validate --rules benchmarks/aws/security.guard --data dist/aws-preparation/benchmark.template.json --output-format json
```

4. Run the campaign from a stable connection. Supply the actual fresh paths in this example:

```powershell
& '.\.bundle-cache\aws-controller\Scripts\python.exe' benchmarks/aws/controller.py --execute --ubuntu-deb 'dist/linux/FactumDB_0.1.0_amd64.deb' --windows-resources 'src-tauri/resources'
```

The default command without `--execute` prepares files offline. The execution command creates and removes real AWS resources and can consume credits. There is no automatic launch date. An existing `campaign-state.json` blocks accidental repeat launches; reconcile its cleanup before attempting another run.

## Results and recovery

The local `dist/aws-campaign/campaign-state.json` contains each stack, instance, bucket, AMI, expiry, artifact SHA-256, SSM status and cleanup outcome. Each run directory contains `results/guest.zip` (summary, samples and logs) plus SSM output. Treat guest/test failures separately from bootstrap, permission, quota and cleanup failures. A failing correctness suite cannot establish the application's RAM requirement.

The independent watchdog terminates expired campaign-owned compute even if the local controller disconnects. Its role cannot terminate other project resources. **It does not delete the full stack.** Stack-wide deletion is the controller's responsibility; if the laptop stops or loses credentials, resume cleanup using AWS MCP and the recorded manifest. Terminate owned instances first, wait for disk deletion, download results, empty the private bucket (including incomplete multipart uploads), then delete only the named campaign stack and verify completion. Reconcile tagged instances, volumes, buckets, roles, profiles, rules, Lambda functions and log groups afterwards. Report leftovers explicitly; never modify existing project resources.

Desktop rendering, interactive native authentication/file dialogs, real-evidence extraction/export throughput and Windows 11 compatibility still require separate finished-application workflows. This harness measures packaged backend readiness, correctness and a synthetic analysis/graph projection; it must not be presented as a complete desktop performance benchmark. RSS is sampled and can double-count shared pages across processes; short-lived child CPU use can be missed. EC2 affinity and different instance families do not reproduce physical CPU clock-speed changes.

## Execution and interrupted-run recovery — 14 October 2026

The current campaign uses revision `c03a50be48ab798220db59ab78502667f67243c8` plus the recorded harness corrections. The Ubuntu installer was compared against 140 backend source and asset hashes. Windows workloads use the packaged embedded Python 3.13.16 runtime; Ubuntu workloads use the packaged backend with Ubuntu 24.04's system Python. Harness dependencies include the current PDF/font requirements.

Guest artifact transfers and result uploads use the disposable guest's instance role rather than URLs tied to a short-lived interactive login. Host uploads use two threads, 16 MiB multipart chunks and bounded SDK retries. The repeatability test explicitly encodes subprocess output as UTF-8 on both sides, including on Windows.

`resume.py STATE` resumes exactly one recorded, running, stack-owned guest without extending its expiry. It rejects guests with commands already submitted or insufficient remaining time. `cleanup.py STATE` recovers full cleanup after an interrupted controller. Completed archives remain local. For a fresh retry campaign, `controller.py --only windows:8 ... --prior-estimated-spend AMOUNT` selects configurations and counts a conservative previous-spend reservation against the USD 16 scheduling limit. These commands execute real AWS operations under the same existing authorization and budget.

`report.py STATE [STATE ...] --output DIRECTORY` combines saved results offline. Keep setup failures in the report; they do not establish application memory requirements. The final report must distinguish Windows Server 2022 from Windows 11 and backend measurements from desktop UI testing.

The full source suite timed out after five minutes on Windows 2 GiB and Ubuntu 1 GiB, while it passed on the corresponding 4 GiB and 8 GiB guests. A focused retry uses `--skip-low-memory-correctness` to keep source-to-package and installed backend checks on these small guests and measure their workload capacity. The retry report marks that the full source suite was skipped there. The initial timeouts remain recorded and should not be mistaken for proof of an application memory failure.

The 14 October campaign finished with all disposable stacks deleted. The final combined report is `dist/aws-benchmark-results-20261014/benchmark-report.md`, with machine-readable JSON/CSV beside it. A separate `resource-inventory.json` records the authenticated AWS inventory and Free Tier API snapshot after cleanup. Following the user's request to stop repetitions, the Windows 2 GiB retry was stopped after its already completed results were uploaded; the Ubuntu 1 GiB retry ran one execution per workload size and CPU limit. Its final attempt was cancelled after out-of-memory events and an overlong response, so only observed early results and the kernel log are available for that guest. Do not infer unrecorded results from that missing archive.
