#!/usr/bin/env python3
"""Add customer request review panel to existing signed Restic Restore UI."""
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
if 'Phase 2D.1: customer restore requests' in s:
    print('ALREADY INSTALLED'); raise SystemExit(0)
old = '''    <section class="rounded border border-outline-gray-2 p-4 space-y-2">
      <h3 class="font-semibold">Recent Restic restore Agent jobs</h3>'''
new = '''    <!-- Phase 2D.1: customer restore requests; never executes or approves restores -->
    <section class="rounded border border-outline-gray-2 p-4 space-y-3">
      <h3 class="font-semibold">Customer restore requests</h3>
      <p class="text-xs text-ink-gray-6">Site administrators submit requests within ERPNext. Review here; preparation and execution remain separate platform actions.</p>
      <div class="flex gap-2 flex-wrap">
        <button type="button" class="rounded border border-outline-gray-2 bg-surface-gray-2 px-3 py-2 text-sm disabled:opacity-50" :disabled="customerBusy" @click="syncCustomerInventory">Sync recovery points to customer site</button>
        <button type="button" class="rounded border border-outline-gray-2 bg-surface-gray-2 px-3 py-2 text-sm disabled:opacity-50" :disabled="customerBusy" @click="loadCustomerRequests">Refresh requests</button>
      </div>
      <p v-if="customerError" class="text-sm text-ink-red-5">{{ customerError }}</p>
      <p v-if="customerMessage" class="text-xs text-ink-gray-6">{{ customerMessage }}</p>
      <div v-if="!customerRequests.length" class="text-sm text-ink-gray-6">No customer requests loaded.</div>
      <div v-else class="overflow-x-auto">
        <table class="w-full text-left text-sm">
          <thead><tr><th class="p-2">Submitted</th><th class="p-2">Requester</th><th class="p-2">Snapshot</th><th class="p-2">Reason</th><th class="p-2">Status</th><th class="p-2">Review</th></tr></thead>
          <tbody><tr v-for="r in customerRequests" :key="r.name">
            <td class="p-2">{{ r.creation }}</td><td class="p-2">{{ r.owner }}</td>
            <td class="p-2 font-mono" :title="r.recovery_point">{{ r.recovery_point?.slice(0,12) }}</td>
            <td class="p-2 max-w-60 break-words">{{ r.reason }}</td><td class="p-2">{{ r.request_state }}</td>
            <td class="p-2"><select class="border rounded p-1" :disabled="customerBusy" :value="r.request_state" @change="reviewCustomerRequest(r, $event.target.value)">
              <option value="Requested" disabled>Requested</option><option value="Acknowledged">Acknowledged</option><option value="Under Review">Under Review</option><option value="Declined">Declined</option>
            </select></td>
          </tr></tbody>
        </table>
      </div>
    </section>
    <section class="rounded border border-outline-gray-2 p-4 space-y-2">
      <h3 class="font-semibold">Recent Restic restore Agent jobs</h3>'''
if s.count(old) != 1:
    raise SystemExit('STOP: Restore panel layout changed; refusing patch')
s=s.replace(old,new)
old='''const restoreResource = createResource({ url: 'press.restic_restore_admin.queue_restore' })'''
new='''const restoreResource = createResource({ url: 'press.restic_restore_admin.queue_restore' })
const customerBusy = ref(false)
const customerError = ref('')
const customerMessage = ref('')
const customerRequests = ref([])
const customerListResource = createResource({ url: 'press.restic_customer_portal_admin.customer_requests' })
const customerSyncResource = createResource({ url: 'press.restic_customer_portal_admin.sync_inventory' })
const customerReviewResource = createResource({ url: 'press.restic_customer_portal_admin.set_customer_request_state' })
async function loadCustomerRequests() {
  customerBusy.value = true
  try {
    const data = unwrap(await customerListResource.submit({site:props.site}))
    customerRequests.value = data.requests || []
    customerMessage.value = `${customerRequests.value.length} customer requests`
    customerError.value = ''
  } catch (e) { customerError.value = getToastErrorMessage(e) }
  finally { customerBusy.value = false }
}
async function syncCustomerInventory() {
  customerBusy.value = true
  try {
    const data = unwrap(await customerSyncResource.submit({site:props.site}))
    customerMessage.value = `Published ${data.count} verified recovery points to customer site`
    customerError.value = ''
  } catch(e) { customerError.value = getToastErrorMessage(e) }
  finally { customerBusy.value = false }
}
async function reviewCustomerRequest(r, state) {
  if (!['Acknowledged','Under Review','Declined'].includes(state)) return
  if (!window.confirm(`Set customer request ${r.name} to ${state}? This does not restore a site.`)) return
  customerBusy.value = true
  try {
    await customerReviewResource.submit({site:props.site, name:r.name, state})
    customerMessage.value = `Request ${r.name} marked ${state}`
    customerError.value = ''
    await loadCustomerRequests()
  } catch(e) { customerError.value = getToastErrorMessage(e) }
  finally { customerBusy.value = false }
}'''
if s.count(old) != 1:
    raise SystemExit('STOP: Vue API layout changed; refusing patch')
s=s.replace(old,new)
p.write_text(s)
print('PASS: Customer request review panel added; no restore execution changes')
