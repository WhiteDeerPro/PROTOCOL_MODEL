# AXI4 executable example guide

This is one unified AXI4 introduction set. A single named runner executes `24` cases and publishes `result.json`, a waveform, and a causality graph for every case. `10` cases exercise legal paths and `14` exercise expected rejection. `FAIL` is a protocol-semantic verdict, not a failed publication.

![Executed evidence organized by theme](coverage.svg)

![Point-to-point structure shared by all cases](topology.svg)

![How the model evidence is produced](evidence-path.svg)

The set uses two honest observation views. In `link-events`, one column is one sequential `CanonicalEvent` input; it does not represent AXI pins, cycles, or VALID/READY. Only `atomic-frames` shows ready/valid lanes sampled at an edge, projecting the normalized internal reset as AXI `ARESETn`.

## Lifecycle

| Case | Input view | Expected → observed | Rule | Evidence |
| --- | --- | --- | --- | --- |
| `read-single-lifecycle`<br>Single read opens and discharges one obligation<br><sub>AR creates one pending read; the matching final R releases it.</sub> | `link-events` | `PASS` → `PASS` | `—` | [wave](cases/read-single-lifecycle/waveform.svg) · [cause](cases/read-single-lifecycle/causality.svg) · [JSON](cases/read-single-lifecycle/result.json) |
| `read-orphan-response`<br>An R response requires a pending AR<br><sub>A response with no pending request is rejected locally.</sub> | `link-events` | `FAIL` → `FAIL` | `axi4.read.orphan_beat` | [wave](cases/read-orphan-response/waveform.svg) · [cause](cases/read-orphan-response/causality.svg) · [JSON](cases/read-orphan-response/result.json) |
| `write-single-lifecycle`<br>AW and W join before B completion<br><sub>The joined write owns one completion resource until B arrives.</sub> | `link-events` | `PASS` → `PASS` | `—` | [wave](cases/write-single-lifecycle/waveform.svg) · [cause](cases/write-single-lifecycle/causality.svg) · [JSON](cases/write-single-lifecycle/result.json) |
| `write-data-before-address`<br>A complete W burst may precede its AW descriptor<br><sub>The ID-less W burst waits in FIFO order and joins the later AW.</sub> | `link-events` | `PASS` → `PASS` | `—` | [wave](cases/write-data-before-address/waveform.svg) · [cause](cases/write-data-before-address/causality.svg) · [JSON](cases/write-data-before-address/result.json) |
| `write-early-wlast` **DEEP DIVE**<br>WLAST follows the oldest AW beat count<br><sub>AWLEN=3 requires four W transfers, so WLAST on beat one is early.</sub> | `atomic-frames` | `FAIL` → `FAIL` | `axi4.write.final_marker` | [wave](cases/write-early-wlast/waveform.svg) · [cause](cases/write-early-wlast/causality.svg) · [JSON](cases/write-early-wlast/result.json) |
| `write-missing-wlast`<br>The final required W transfer asserts WLAST<br><sub>A single-beat AW requires WLAST on its only W transfer.</sub> | `link-events` | `FAIL` → `FAIL` | `axi4.write.final_marker` | [wave](cases/write-missing-wlast/waveform.svg) · [cause](cases/write-missing-wlast/causality.svg) · [JSON](cases/write-missing-wlast/result.json) |
| `write-wrong-bid`<br>BID identifies a pending write context<br><sub>A B response for ID 13 cannot complete the joined write for ID 12.</sub> | `link-events` | `FAIL` → `FAIL` | `axi4.exclusive.orphan_write_response` | [wave](cases/write-wrong-bid/waveform.svg) · [cause](cases/write-wrong-bid/causality.svg) · [JSON](cases/write-wrong-bid/result.json) |

<details>
<summary>View waveform and causality for `read-single-lifecycle`</summary>

**Single read opens and discharges one obligation.** AR creates one pending read; the matching final R releases it.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![Single read opens and discharges one obligation waveform](cases/read-single-lifecycle/waveform.svg)

![Single read opens and discharges one obligation causality](cases/read-single-lifecycle/causality.svg)

[result.json](cases/read-single-lifecycle/result.json) · [WaveJSON](sources/cases/read-single-lifecycle/waveform.json) · [DOT](sources/cases/read-single-lifecycle/causality.dot)

</details>

<details>
<summary>View waveform and causality for `read-orphan-response`</summary>

**An R response requires a pending AR.** A response with no pending request is rejected locally.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![An R response requires a pending AR waveform](cases/read-orphan-response/waveform.svg)

![An R response requires a pending AR causality](cases/read-orphan-response/causality.svg)

[result.json](cases/read-orphan-response/result.json) · [WaveJSON](sources/cases/read-orphan-response/waveform.json) · [DOT](sources/cases/read-orphan-response/causality.dot)

</details>

<details>
<summary>View waveform and causality for `write-single-lifecycle`</summary>

**AW and W join before B completion.** The joined write owns one completion resource until B arrives.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![AW and W join before B completion waveform](cases/write-single-lifecycle/waveform.svg)

![AW and W join before B completion causality](cases/write-single-lifecycle/causality.svg)

[result.json](cases/write-single-lifecycle/result.json) · [WaveJSON](sources/cases/write-single-lifecycle/waveform.json) · [DOT](sources/cases/write-single-lifecycle/causality.dot)

</details>

<details>
<summary>View waveform and causality for `write-data-before-address`</summary>

**A complete W burst may precede its AW descriptor.** The ID-less W burst waits in FIFO order and joins the later AW.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![A complete W burst may precede its AW descriptor waveform](cases/write-data-before-address/waveform.svg)

![A complete W burst may precede its AW descriptor causality](cases/write-data-before-address/causality.svg)

[result.json](cases/write-data-before-address/result.json) · [WaveJSON](sources/cases/write-data-before-address/waveform.json) · [DOT](sources/cases/write-data-before-address/causality.dot)

</details>

<details>
<summary>View waveform and causality for `write-missing-wlast`</summary>

**The final required W transfer asserts WLAST.** A single-beat AW requires WLAST on its only W transfer.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![The final required W transfer asserts WLAST waveform](cases/write-missing-wlast/waveform.svg)

![The final required W transfer asserts WLAST causality](cases/write-missing-wlast/causality.svg)

[result.json](cases/write-missing-wlast/result.json) · [WaveJSON](sources/cases/write-missing-wlast/waveform.json) · [DOT](sources/cases/write-missing-wlast/causality.dot)

</details>

<details>
<summary>View waveform and causality for `write-wrong-bid`</summary>

**BID identifies a pending write context.** A B response for ID 13 cannot complete the joined write for ID 12.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![BID identifies a pending write context waveform](cases/write-wrong-bid/waveform.svg)

![BID identifies a pending write context causality](cases/write-wrong-bid/causality.svg)

[result.json](cases/write-wrong-bid/result.json) · [WaveJSON](sources/cases/write-wrong-bid/waveform.json) · [DOT](sources/cases/write-wrong-bid/causality.dot)

</details>

## Geometry

| Case | Input view | Expected → observed | Rule | Evidence |
| --- | --- | --- | --- | --- |
| `read-crosses-4kb-boundary`<br>An INCR burst stays within one 4KB region<br><sub>Two four-byte transfers starting at 0xFFC cross the boundary.</sub> | `link-events` | `FAIL` → `FAIL` | `axi4.link_session.AR.event_schema` | [wave](cases/read-crosses-4kb-boundary/waveform.svg) · [cause](cases/read-crosses-4kb-boundary/causality.svg) · [JSON](cases/read-crosses-4kb-boundary/result.json) |
| `write-narrow-unaligned-incr` **DEEP DIVE**<br>Narrow unaligned transfers rotate legal byte lanes<br><sub>The four legal WSTRB masks are derived from the AW geometry.</sub> | `atomic-frames` | `PASS` → `PASS` | `—` | [wave](cases/write-narrow-unaligned-incr/waveform.svg) · [cause](cases/write-narrow-unaligned-incr/causality.svg) · [JSON](cases/write-narrow-unaligned-incr/result.json) |
| `write-strobe-outside-lanes`<br>WSTRB cannot select bytes outside the transfer container<br><sub>At address 0x3 only lane 3 is legal for this first transfer.</sub> | `link-events` | `FAIL` → `FAIL` | `axi4.write.byte_lanes` | [wave](cases/write-strobe-outside-lanes/waveform.svg) · [cause](cases/write-strobe-outside-lanes/causality.svg) · [JSON](cases/write-strobe-outside-lanes/result.json) |
| `read-wrap-four-legal`<br>A four-transfer WRAP burst rotates inside its wrap window<br><sub>Starting at 0x2C produces a legal four-transfer wrap in 0x20–0x2F.</sub> | `link-events` | `PASS` → `PASS` | `—` | [wave](cases/read-wrap-four-legal/waveform.svg) · [cause](cases/read-wrap-four-legal/causality.svg) · [JSON](cases/read-wrap-four-legal/result.json) |
| `read-wrap-three-illegal`<br>WRAP uses one of the protocol's permitted transfer counts<br><sub>Three transfers are not a legal AXI4 WRAP length.</sub> | `link-events` | `FAIL` → `FAIL` | `axi4.link_session.AR.event_schema` | [wave](cases/read-wrap-three-illegal/waveform.svg) · [cause](cases/read-wrap-three-illegal/causality.svg) · [JSON](cases/read-wrap-three-illegal/result.json) |
| `read-fixed-sixteen-legal`<br>FIXED permits sixteen transfers at one address container<br><sub>Even at 0xFFF, every transfer reuses the same in-page container.</sub> | `link-events` | `PASS` → `PASS` | `—` | [wave](cases/read-fixed-sixteen-legal/waveform.svg) · [cause](cases/read-fixed-sixteen-legal/causality.svg) · [JSON](cases/read-fixed-sixteen-legal/result.json) |
| `read-fixed-seventeen-illegal`<br>FIXED length does not exceed sixteen transfers<br><sub>AxLEN=16 encodes seventeen transfers and is rejected for FIXED.</sub> | `link-events` | `FAIL` → `FAIL` | `axi4.link_session.AR.event_schema` | [wave](cases/read-fixed-seventeen-illegal/waveform.svg) · [cause](cases/read-fixed-seventeen-illegal/causality.svg) · [JSON](cases/read-fixed-seventeen-illegal/result.json) |

<details>
<summary>View waveform and causality for `read-crosses-4kb-boundary`</summary>

**An INCR burst stays within one 4KB region.** Two four-byte transfers starting at 0xFFC cross the boundary.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![An INCR burst stays within one 4KB region waveform](cases/read-crosses-4kb-boundary/waveform.svg)

![An INCR burst stays within one 4KB region causality](cases/read-crosses-4kb-boundary/causality.svg)

[result.json](cases/read-crosses-4kb-boundary/result.json) · [WaveJSON](sources/cases/read-crosses-4kb-boundary/waveform.json) · [DOT](sources/cases/read-crosses-4kb-boundary/causality.dot)

</details>

<details>
<summary>View waveform and causality for `write-strobe-outside-lanes`</summary>

**WSTRB cannot select bytes outside the transfer container.** At address 0x3 only lane 3 is legal for this first transfer.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![WSTRB cannot select bytes outside the transfer container waveform](cases/write-strobe-outside-lanes/waveform.svg)

![WSTRB cannot select bytes outside the transfer container causality](cases/write-strobe-outside-lanes/causality.svg)

[result.json](cases/write-strobe-outside-lanes/result.json) · [WaveJSON](sources/cases/write-strobe-outside-lanes/waveform.json) · [DOT](sources/cases/write-strobe-outside-lanes/causality.dot)

</details>

<details>
<summary>View waveform and causality for `read-wrap-four-legal`</summary>

**A four-transfer WRAP burst rotates inside its wrap window.** Starting at 0x2C produces a legal four-transfer wrap in 0x20–0x2F.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![A four-transfer WRAP burst rotates inside its wrap window waveform](cases/read-wrap-four-legal/waveform.svg)

![A four-transfer WRAP burst rotates inside its wrap window causality](cases/read-wrap-four-legal/causality.svg)

[result.json](cases/read-wrap-four-legal/result.json) · [WaveJSON](sources/cases/read-wrap-four-legal/waveform.json) · [DOT](sources/cases/read-wrap-four-legal/causality.dot)

</details>

<details>
<summary>View waveform and causality for `read-wrap-three-illegal`</summary>

**WRAP uses one of the protocol's permitted transfer counts.** Three transfers are not a legal AXI4 WRAP length.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![WRAP uses one of the protocol's permitted transfer counts waveform](cases/read-wrap-three-illegal/waveform.svg)

![WRAP uses one of the protocol's permitted transfer counts causality](cases/read-wrap-three-illegal/causality.svg)

[result.json](cases/read-wrap-three-illegal/result.json) · [WaveJSON](sources/cases/read-wrap-three-illegal/waveform.json) · [DOT](sources/cases/read-wrap-three-illegal/causality.dot)

</details>

<details>
<summary>View waveform and causality for `read-fixed-sixteen-legal`</summary>

**FIXED permits sixteen transfers at one address container.** Even at 0xFFF, every transfer reuses the same in-page container.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![FIXED permits sixteen transfers at one address container waveform](cases/read-fixed-sixteen-legal/waveform.svg)

![FIXED permits sixteen transfers at one address container causality](cases/read-fixed-sixteen-legal/causality.svg)

[result.json](cases/read-fixed-sixteen-legal/result.json) · [WaveJSON](sources/cases/read-fixed-sixteen-legal/waveform.json) · [DOT](sources/cases/read-fixed-sixteen-legal/causality.dot)

</details>

<details>
<summary>View waveform and causality for `read-fixed-seventeen-illegal`</summary>

**FIXED length does not exceed sixteen transfers.** AxLEN=16 encodes seventeen transfers and is rejected for FIXED.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![FIXED length does not exceed sixteen transfers waveform](cases/read-fixed-seventeen-illegal/waveform.svg)

![FIXED length does not exceed sixteen transfers causality](cases/read-fixed-seventeen-illegal/causality.svg)

[result.json](cases/read-fixed-seventeen-illegal/result.json) · [WaveJSON](sources/cases/read-fixed-seventeen-illegal/waveform.json) · [DOT](sources/cases/read-fixed-seventeen-illegal/causality.dot)

</details>

## Ordering / interleave

| Case | Input view | Expected → observed | Rule | Evidence |
| --- | --- | --- | --- | --- |
| `read-cross-id-interleave`<br>Responses for different IDs may interleave<br><sub>Each ID keeps its own beat count while the link alternates IDs.</sub> | `link-events` | `PASS` → `PASS` | `—` | [wave](cases/read-cross-id-interleave/waveform.svg) · [cause](cases/read-cross-id-interleave/causality.svg) · [JSON](cases/read-cross-id-interleave/result.json) |
| `read-same-id-later-cannot-overtake`<br>The oldest same-ID read consumes responses first<br><sub>A final beat shaped for the later one-beat read is early for the oldest read.</sub> | `link-events` | `FAIL` → `FAIL` | `axi4.read.final_marker` | [wave](cases/read-same-id-later-cannot-overtake/waveform.svg) · [cause](cases/read-same-id-later-cannot-overtake/causality.svg) · [JSON](cases/read-same-id-later-cannot-overtake/result.json) |
| `write-multiple-outstanding-reverse-b`<br>Different write IDs may complete in reverse request order<br><sub>W remains FIFO-correlated with AW while B selects pending writes by ID.</sub> | `link-events` | `PASS` → `PASS` | `—` | [wave](cases/write-multiple-outstanding-reverse-b/waveform.svg) · [cause](cases/write-multiple-outstanding-reverse-b/causality.svg) · [JSON](cases/write-multiple-outstanding-reverse-b/result.json) |

<details>
<summary>View waveform and causality for `read-cross-id-interleave`</summary>

**Responses for different IDs may interleave.** Each ID keeps its own beat count while the link alternates IDs.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![Responses for different IDs may interleave waveform](cases/read-cross-id-interleave/waveform.svg)

![Responses for different IDs may interleave causality](cases/read-cross-id-interleave/causality.svg)

[result.json](cases/read-cross-id-interleave/result.json) · [WaveJSON](sources/cases/read-cross-id-interleave/waveform.json) · [DOT](sources/cases/read-cross-id-interleave/causality.dot)

</details>

<details>
<summary>View waveform and causality for `read-same-id-later-cannot-overtake`</summary>

**The oldest same-ID read consumes responses first.** A final beat shaped for the later one-beat read is early for the oldest read.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![The oldest same-ID read consumes responses first waveform](cases/read-same-id-later-cannot-overtake/waveform.svg)

![The oldest same-ID read consumes responses first causality](cases/read-same-id-later-cannot-overtake/causality.svg)

[result.json](cases/read-same-id-later-cannot-overtake/result.json) · [WaveJSON](sources/cases/read-same-id-later-cannot-overtake/waveform.json) · [DOT](sources/cases/read-same-id-later-cannot-overtake/causality.dot)

</details>

<details>
<summary>View waveform and causality for `write-multiple-outstanding-reverse-b`</summary>

**Different write IDs may complete in reverse request order.** W remains FIFO-correlated with AW while B selects pending writes by ID.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![Different write IDs may complete in reverse request order waveform](cases/write-multiple-outstanding-reverse-b/waveform.svg)

![Different write IDs may complete in reverse request order causality](cases/write-multiple-outstanding-reverse-b/causality.svg)

[result.json](cases/write-multiple-outstanding-reverse-b/result.json) · [WaveJSON](sources/cases/write-multiple-outstanding-reverse-b/waveform.json) · [DOT](sources/cases/write-multiple-outstanding-reverse-b/causality.dot)

</details>

## Observation / reset

| Case | Input view | Expected → observed | Rule | Evidence |
| --- | --- | --- | --- | --- |
| `observation-same-frame-aw-w`<br>AW and W at one edge commit as one frame<br><sub>The observation lowering correlates both transfers before the later B.</sub> | `atomic-frames` | `PASS` → `PASS` | `—` | [wave](cases/observation-same-frame-aw-w/waveform.svg) · [cause](cases/observation-same-frame-aw-w/causality.svg) · [JSON](cases/observation-same-frame-aw-w/result.json) |
| `observation-same-frame-ar-r`<br>A response cannot consume an obligation born at the same edge<br><sub>R is checked against state visible before the current AR commits.</sub> | `atomic-frames` | `FAIL` → `FAIL` | `axi4.read.orphan_beat` | [wave](cases/observation-same-frame-ar-r/waveform.svg) · [cause](cases/observation-same-frame-ar-r/causality.svg) · [JSON](cases/observation-same-frame-ar-r/result.json) |
| `observation-stalled-payload-mutation`<br>Payload remains stable while VALID is stalled<br><sub>Changing ARADDR before acceptance violates ready/valid stability.</sub> | `atomic-frames` | `FAIL` → `FAIL` | `axi4.observation.AR.ready_valid.payload_stability` | [wave](cases/observation-stalled-payload-mutation/waveform.svg) · [cause](cases/observation-stalled-payload-mutation/causality.svg) · [JSON](cases/observation-stalled-payload-mutation/result.json) |
| `observation-reset-clears-pending-read`<br>Reset starts a new observation and link epoch<br><sub>An R after reset cannot complete the pre-reset AR.</sub> | `atomic-frames` | `FAIL` → `FAIL` | `axi4.read.orphan_beat` | [wave](cases/observation-reset-clears-pending-read/waveform.svg) · [cause](cases/observation-reset-clears-pending-read/causality.svg) · [JSON](cases/observation-reset-clears-pending-read/result.json) |

<details>
<summary>View waveform and causality for `observation-same-frame-aw-w`</summary>

**AW and W at one edge commit as one frame.** The observation lowering correlates both transfers before the later B.

This waveform projects ready/valid samples from AtomicFrame.

![AW and W at one edge commit as one frame waveform](cases/observation-same-frame-aw-w/waveform.svg)

![AW and W at one edge commit as one frame causality](cases/observation-same-frame-aw-w/causality.svg)

[result.json](cases/observation-same-frame-aw-w/result.json) · [WaveJSON](sources/cases/observation-same-frame-aw-w/waveform.json) · [DOT](sources/cases/observation-same-frame-aw-w/causality.dot)

</details>

<details>
<summary>View waveform and causality for `observation-same-frame-ar-r`</summary>

**A response cannot consume an obligation born at the same edge.** R is checked against state visible before the current AR commits.

This waveform projects ready/valid samples from AtomicFrame.

![A response cannot consume an obligation born at the same edge waveform](cases/observation-same-frame-ar-r/waveform.svg)

![A response cannot consume an obligation born at the same edge causality](cases/observation-same-frame-ar-r/causality.svg)

[result.json](cases/observation-same-frame-ar-r/result.json) · [WaveJSON](sources/cases/observation-same-frame-ar-r/waveform.json) · [DOT](sources/cases/observation-same-frame-ar-r/causality.dot)

</details>

<details>
<summary>View waveform and causality for `observation-stalled-payload-mutation`</summary>

**Payload remains stable while VALID is stalled.** Changing ARADDR before acceptance violates ready/valid stability.

This waveform projects ready/valid samples from AtomicFrame.

![Payload remains stable while VALID is stalled waveform](cases/observation-stalled-payload-mutation/waveform.svg)

![Payload remains stable while VALID is stalled causality](cases/observation-stalled-payload-mutation/causality.svg)

[result.json](cases/observation-stalled-payload-mutation/result.json) · [WaveJSON](sources/cases/observation-stalled-payload-mutation/waveform.json) · [DOT](sources/cases/observation-stalled-payload-mutation/causality.dot)

</details>

<details>
<summary>View waveform and causality for `observation-reset-clears-pending-read`</summary>

**Reset starts a new observation and link epoch.** An R after reset cannot complete the pre-reset AR.

This waveform projects ready/valid samples from AtomicFrame.

![Reset starts a new observation and link epoch waveform](cases/observation-reset-clears-pending-read/waveform.svg)

![Reset starts a new observation and link epoch causality](cases/observation-reset-clears-pending-read/causality.svg)

[result.json](cases/observation-reset-clears-pending-read/result.json) · [WaveJSON](sources/cases/observation-reset-clears-pending-read/waveform.json) · [DOT](sources/cases/observation-reset-clears-pending-read/causality.dot)

</details>

## Exclusive / profile

| Case | Input view | Expected → observed | Rule | Evidence |
| --- | --- | --- | --- | --- |
| `exclusive-matching-exokay`<br>A matching link-local exclusive sequence may succeed<br><sub>The completed exclusive read makes one matching write eligible for EXOKAY.</sub> | `link-events` | `PASS` → `PASS` | `—` | [wave](cases/exclusive-matching-exokay/waveform.svg) · [cause](cases/exclusive-matching-exokay/causality.svg) · [JSON](cases/exclusive-matching-exokay/result.json) |
| `profile-bounded-read-capacity`<br>A refined profile can bound outstanding reads<br><sub>The second AR exceeds a configured capacity of one and is rolled back.</sub> | `link-events` | `FAIL` → `FAIL` | `axi4_one_read.axi4.read.pending_transactions.capacity` | [wave](cases/profile-bounded-read-capacity/waveform.svg) · [cause](cases/profile-bounded-read-capacity/causality.svg) · [JSON](cases/profile-bounded-read-capacity/result.json) |
| `exclusive-unmatched-success`<br>EXOKAY requires a matching completed exclusive read<br><sub>An exclusive write without a reservation may complete, but not with EXOKAY.</sub> | `link-events` | `FAIL` → `FAIL` | `axi4.exclusive.unmatched_success` | [wave](cases/exclusive-unmatched-success/waveform.svg) · [cause](cases/exclusive-unmatched-success/causality.svg) · [JSON](cases/exclusive-unmatched-success/result.json) |

<details>
<summary>View waveform and causality for `exclusive-matching-exokay`</summary>

**A matching link-local exclusive sequence may succeed.** The completed exclusive read makes one matching write eligible for EXOKAY.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![A matching link-local exclusive sequence may succeed waveform](cases/exclusive-matching-exokay/waveform.svg)

![A matching link-local exclusive sequence may succeed causality](cases/exclusive-matching-exokay/causality.svg)

[result.json](cases/exclusive-matching-exokay/result.json) · [WaveJSON](sources/cases/exclusive-matching-exokay/waveform.json) · [DOT](sources/cases/exclusive-matching-exokay/causality.dot)

</details>

<details>
<summary>View waveform and causality for `profile-bounded-read-capacity`</summary>

**A refined profile can bound outstanding reads.** The second AR exceeds a configured capacity of one and is rolled back.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![A refined profile can bound outstanding reads waveform](cases/profile-bounded-read-capacity/waveform.svg)

![A refined profile can bound outstanding reads causality](cases/profile-bounded-read-capacity/causality.svg)

[result.json](cases/profile-bounded-read-capacity/result.json) · [WaveJSON](sources/cases/profile-bounded-read-capacity/waveform.json) · [DOT](sources/cases/profile-bounded-read-capacity/causality.dot)

</details>

<details>
<summary>View waveform and causality for `exclusive-unmatched-success`</summary>

**EXOKAY requires a matching completed exclusive read.** An exclusive write without a reservation may complete, but not with EXOKAY.

One event-level column is one CanonicalEvent, not pin/cycle timing.

![EXOKAY requires a matching completed exclusive read waveform](cases/exclusive-unmatched-success/waveform.svg)

![EXOKAY requires a matching completed exclusive read causality](cases/exclusive-unmatched-success/causality.svg)

[result.json](cases/exclusive-unmatched-success/result.json) · [WaveJSON](sources/cases/exclusive-unmatched-success/waveform.json) · [DOT](sources/cases/exclusive-unmatched-success/causality.dot)

</details>

## Two narrated deep dives

These are the same cases and the same executions already listed above. They do not increase the case count or introduce a second checker; they only use richer `AtomicFrame` input and expanded explanation.

### `write-early-wlast` — WLAST follows the oldest AW beat count

The trace keeps the same AW descriptor and changes only the first beat's WLAST to 1. From AWLEN=3 the model derives that three beats remain and rejects the atomic commit under `axi4.write.final_marker`.

`ARESETn` is the AXI-facing inverse of the model's normalized active-high `reset`; `FIRE` is derived as `VALID && READY`, not sampled from additional RTL pins.

![WLAST follows the oldest AW beat count waveform](cases/write-early-wlast/waveform.svg)

![WLAST follows the oldest AW beat count causality](cases/write-early-wlast/causality.svg)

[result.json](cases/write-early-wlast/result.json) · [WaveJSON](sources/cases/write-early-wlast/waveform.json) · [DOT](sources/cases/write-early-wlast/causality.dot)

### `write-narrow-unaligned-incr` — Narrow unaligned transfers rotate legal byte lanes

The trace starts in reset. AWLEN=3 declares four write transfers; the four W beats expose rotating WSTRB masks for the unaligned narrow access, the final beat asserts WLAST, and B completes and releases the transaction resources.

`ARESETn` is the AXI-facing inverse of the model's normalized active-high `reset`; `FIRE` is derived as `VALID && READY`, not sampled from additional RTL pins.

![Narrow unaligned transfers rotate legal byte lanes waveform](cases/write-narrow-unaligned-incr/waveform.svg)

![Narrow unaligned transfers rotate legal byte lanes causality](cases/write-narrow-unaligned-incr/causality.svg)

[result.json](cases/write-narrow-unaligned-incr/result.json) · [WaveJSON](sources/cases/write-narrow-unaligned-incr/waveform.json) · [DOT](sources/cases/write-narrow-unaligned-incr/causality.dot)

## Evidence boundary and provenance

`24/24` cases met their declared expectations. Case count describes representative samples that were executed; it is not AXI4 requirement coverage or RTL compliance evidence. See [examples.json](examples.json) for aggregation, [provenance.json](provenance.json) for origin, and [manifest.json](manifest.json) for the artifact inventory.
