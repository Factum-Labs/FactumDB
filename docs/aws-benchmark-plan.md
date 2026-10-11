# Sydney benchmark plan

This updates the future Windows and Ubuntu tests using read-only AWS capability checks from 11 October 2026. This document does not launch resources. The integration phase remains read-only.

Implementation and launch/recovery commands are prepared in [AWS testing](aws-testing.md). The restarted MCP authentication check has passed. The seven-machine campaign has an initial USD 4.08006 forecast, including a USD 3 ancillary allowance; reprice before execution. No machines are scheduled.

## Verified constraints

The project has an active Free plan with USD 100 remaining credits and plan expiration 11 April 2027. The combined benchmark budget remains **USD 20**, regardless of the available balance. Use profile `factumdb-benchmark`; every benchmark resource stays in `ap-southeast-2`.

| Instance type | RAM GiB | vCPUs | Planned use |
|---|---:|---:|---|
| t3.micro | 1 | 2 | Ubuntu low-memory boundary |
| t3.small | 2 | 2 | Ubuntu and Windows low-memory checks |
| c7i-flex.large | 4 | 2 | Ubuntu and Windows middle configuration |
| m7i-flex.large | 8 | 2 | Ubuntu and Windows baseline |

All four types are Free Tier eligible and offered in Sydney at verification time. Standard On-Demand quota `L-1216C47A` is **5 vCPUs**, with no existing Sydney instances found. Run one test instance at a time to leave room for unexpected project usage. A successful dry-run does not guarantee launch capacity.

| Guest | Selected eligible AMI | AMI root disk minimum |
|---|---|---:|
| Ubuntu 24.04 x86-64 | `ami-0f5e1e0151e5b95ed` | 8 GiB |
| Windows Server 2022 Full Base x86-64 | `ami-0cf95ca5b969cc689` | 30 GiB |

Revalidate AMI availability, Free-plan eligibility and quotas immediately before launch. Use encrypted gp3 root volumes with deletion on termination, sized for the build and fixtures; 40 GiB is the initial proposed size for each guest. Windows Server results establish a server-OS baseline; Windows 11 requirements need separate validation.

## Test campaign

1. Inspect the current application and its existing benchmarks, establish representative workflows and fixtures, then build reproducible Ubuntu and Windows artifacts from one revision. Separate build/install time from application performance.
2. Start with 8 GiB/2 vCPUs on each OS. Verify installation, startup, representative imports, queries, correlation and graph operations, and export. Record completion, correctness, wall time, peak process memory, total guest memory, CPU utilization, paging, disk and crashes. Run repeat measurements after a warm-up.
3. Test 4 GiB and 2 GiB configurations, plus Ubuntu at 1 GiB if the guest and workload can start. Record OS/automation overhead separately. A failure to boot or launch the test harness is an untested application configuration, not proof of the application's RAM requirement.
4. All eligible types have two vCPUs. Compare one versus two available CPUs using documented process affinity where supported, labeling this as an application CPU restriction. It does not reproduce a one-vCPU VM or a specific processor clock speed. Record the reported processor and CPU entitlement; T3 burst credits and the different Flex families can confound comparisons. Use a consistent instance family with controlled memory limits if an isolated RAM comparison is needed, then confirm the boundary on the actual smaller instance.
5. Report minimum successful and recommended configurations per workflow and fixture size. Keep correctness and responsiveness criteria explicit; do not infer physical-PC processor-speed requirements directly from EC2 timings. Verify desktop UI flows separately if guest automation cannot exercise them.

## Budget and cleanup before launch

Obtain current Sydney prices for Linux and Windows instances, gp3 storage, public IPv4, S3 and watchdog/logging services before determining runtime limits. Use a local cost estimate and resource manifest; billing data can lag. Stop scheduling at **USD 16 estimated use**, reserving **USD 4** for shutdown and uncertainty. This is an operational budget, not a guaranteed billing cap.

Before creating a test machine, prepare an independent Lambda/EventBridge watchdog with a fixed expiration and permissions limited to this campaign's resource IDs/tags. Verify it can terminate the test instance and clean up tagged dependencies. Also set instance-local shutdown as a secondary measure and use `try/finally` cleanup in the controller. Do not rely solely on the local laptop or an AWS budget alert.

Use Systems Manager for test execution, avoid public inbound management ports, and keep temporary artifacts in a private Sydney S3 bucket. Avoid NAT gateways, idle addresses and unnecessary services. Write permissions for role creation/PassRole, SSM commands, S3 uploads and watchdog deployment are still unverified; resolve these in the provisioning phase before starting tests.

Terminate each disposable instance after its results are saved. Remove its remaining volumes, campaign snapshots/images, temporary artifact objects/bucket, logging resources, watchdog schedules/functions and campaign-created IAM roles/policies. Preserve existing project resources. Reconcile the manifest with live inventory after cleanup and report any leftovers explicitly. Retain the final report locally before deleting AWS copies.

Both AMI launch dry-runs passed using `m7i-flex.large` in a default subnet without an instance role. EC2/EBS, S3, Systems Manager, Lambda, EventBridge, CloudWatch, IAM, STS and Service Quotas read checks passed. Actual launches, execution, role attachment and cleanup remain untested. Detailed evidence is in `dist/aws-verification/report.md` and `capabilities.json`.
