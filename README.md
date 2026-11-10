# Frappe Press Restic Phase 2D.1 — customer restore request pilot

**Purpose:** Add tenant-local, administrator-initiated *requests* for Restic recovery, and a Press administrator intake view. This release DOES NOT initiate or approve restores, does NOT access Restic vaults, and does NOT change the existing Backup01→F-node restoration flow. Backup02 is not used.

## Deliverables

1. `app/frappe_restic_portal/`: maintained standalone Frappe app for the managed **Standard v16 Release Group `bench-0002`**, not an untracked edit inside a running container.
2. `press/`: signed site inventory sync and customer request polling/status via HTTPS, plus an additive review section in the existing Press Restore tab.
3. `tests/`: local protocol/security tests.

This is an **initial pilot package**. Local tests do not prove it works on the managed release group. Test on `erp-standard-test.frappe.netlinkz.co.za` before other customers.

## Why a separate app

The customer's Frappe/ERPNext site has its own DB/user authentication. Press is an internal/VPN-only control plane, and backup data remains on Backup01. The new app contains only metadata and a request DocType: customers never log into Press or access Backup01/Backup02. This app should be maintained in a private Git repository and deployed through Press Release Groups to survive bench image upgrades.

## Installation sequence

**A. Install the tenant app via the managed Release Group:**

1. Create/push a **private repository** containing exactly the contents of `app/frappe_restic_portal/` at the repo root. Do not include Press signing keys, site configs, data files or the `/root` deployment packages.
2. Add the app repository to the **Standard v16** Release Group `bench-0002` in Press, build the new release, and deploy it to F03. Follow the usual controlled release flow. Do **not** `pip install` inside a running managed container; the change would not persist across releases.
3. Within Press, install **frappe_restic_portal** on pilot site `erp-standard-test.frappe.netlinkz.co.za` only. Frappe creates three DocTypes: `Restic Recovery Point`, `Restic Restore Request`, `Restic Platform Message`.
4. Copy **only the Press public key** from Press01 `/home/frappe/.config/frappe-restic-policy/press-signing.pub` to F03 site **host** path:
   `/home/frappe/benches/bench-0002-000001-frappe-f03/sites/erp-standard-test.frappe.netlinkz.co.za/private/restic-press-public.pem`
   Set owner `frappe:frappe`, mode `0644`; check the site container can read the file. The *private* signing key remains exclusively on Press01. Use the already trusted transfer process. Never transfer the private key.

**B. Install the Press administrator bridge:**

Copy this ZIP to Press01, extract in `/root`, and as **root** run:

```bash
bash /root/frappe-restic-phase2d1/press/install.sh
```

Then as `frappe`:

```bash
cd /home/frappe/press-bench/apps/press/dashboard && npm run build
```

Then as root:

```bash
supervisorctl restart 'press-bench-web:*'
printf '{"enabled":false}\n' > /etc/frappe-restic/restore-admin-ui.json
```

`press/install.sh` does not enable the restore execution gate and does not restart the scheduler, workers, or backup services.

**C. Customer pilot:**

1. In Press → pilot Site → Restic Restore, refresh the signed Backup01 catalogue if older than six hours, then click **Sync recovery points to customer site**.
2. On the pilot ERPNext site as a **System Manager**, open `Restic Recovery Point` and verify the list (the records are read-only).
3. Create a `Restic Restore Request`, select a recovery point, enter a reason, save. Request state must be `Requested`; editing/deletion is not available to customers.
4. In Press → Restic Restore click **Refresh requests**. Confirm the request, site, requester, reason and full selected snapshot ID; mark it **Acknowledged** or **Under Review**. The new status should show in ERPNext.
5. **Do not issue F03 root approval or enable the Press live execution gate** during this test.

## Security characteristics

- Site API `platform_exchange` accepts **only signed** Press messages with a **distinct domain separator** and a registered per-site Press public key. It rejects wrong tenant, unknown action, stale timestamp, malformed signature and reused request ID.
- This API is HTTPS-accessible on the customer site but accepts **no general site-admin authentication in lieu of a valid platform signature** for sync/review actions. Use your usual HTTPS TLS validation; Press never follows redirects or accepts arbitrary target URLs.
- Customer form uses Frappe's built-in System Manager role and DocType permissions. User-submitted requests are immutable; the platform enforces the actual snapshot against Backup01's verified inventory before preparation. A user-submitted request has **zero execution privileges**.
- The platform can mark only **Acknowledged**, **Under Review**, or **Declined** in Phase 2D.1; it cannot fabricate a successful restore status through this module.
- The Press bridge needs only the current Press signing key already used by the signed restore system. **Neither Press nor the site app gets Backup01 or Backup02 Restic credentials**.

## Known scope limits / follow-up

- Phase 2D.1 is **a pilot with a manual administrator review** in Press. Automatic periodic request intake, customer status updates tied to actual Agent Job state, role delegation beyond System Manager, and platform-managed rotation of the trusted public key are separate next steps.
- The Press host needs network/TLS access to the site's HTTPS endpoint. This does not expose Press01 inbound to the Internet.
- The Restore Request is a customer request, not a production restore approval. Independent F03 root approval, Press execution gate, rollback creation and existing Agent job protections remain mandatory.
- Shared bench rollout must be checked for app/version compatibility and for surviving restores from snapshots predating the portal app.

## Validation

```bash
python3 -m unittest discover -s tests -v
```

Seven local tests cover Ed25519 signature, cross-protocol isolation, tenant isolation, expiry, invalid actions, role restrictions, and absence of live restore code. Vue patch is also dry-run tested against the Phase 2C.7C component.
