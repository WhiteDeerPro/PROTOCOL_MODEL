"""Observed CHI transaction flows projected into protocol-neutral view IR.

This module deliberately starts from accepted participant transitions.  It
does not reconstruct CHI behavior from opcode order, and it does not claim a
pin-, flit-, or cycle-accurate waveform.  Network-scheduled runs and
scenario-controlled participant runs can both retain the same small
``ChiOperationObservationStep`` boundary before they are rendered.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from protocol_model.visualization import (
    EvidenceBasis,
    MessageObservationPoint,
    TimeBasis,
    TimeSpaceCausalEdge,
    TimeSpaceLifeline,
    TimeSpaceMessage,
    TimeSpaceStateChange,
    TransactionTimeSpaceView,
    ViewScope,
)

from .participants.coherence import ChiRnCopyBackOutcome
from .representation import (
    ChiChannelKind,
    ChiCompDataMessage,
    ChiCompDBIDRespMessage,
    ChiCompMessage,
    ChiCopyBackWrDataMessage,
    ChiNetworkPacket,
    ChiPCrdGrantMessage,
    ChiRetryAckMessage,
    ChiSnpCleanInvalidMessage,
    ChiSnpRespDataMessage,
    ChiSnpRespMessage,
)
from .system.coherence import ChiCoherenceState
from .system.coherence_network import (
    ChiCoherenceNetworkEvent,
    ChiCoherenceNetworkEventKind,
    ChiCoherenceNetworkSession,
    ChiCoherenceNetworkState,
)


@dataclass(frozen=True)
class ChiFlowParticipant:
    """One NodeID/lifeline association supplied by resolved construction."""

    node_id: int
    ref: str
    label: str
    role: str
    display_fields: Mapping[str, object] = MappingProxyType({})

    def __post_init__(self) -> None:
        if (
            not isinstance(self.node_id, int)
            or isinstance(self.node_id, bool)
            or self.node_id < 0
        ):
            raise ValueError("CHI flow participant requires a NodeID")
        for name, value in (
            ("ref", self.ref),
            ("label", self.label),
            ("role", self.role),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"CHI flow participant requires {name}")
        if not isinstance(self.display_fields, Mapping):
            raise TypeError("participant display_fields must be a mapping")
        validated_lifeline = TimeSpaceLifeline(
            self.ref,
            self.label,
            self.role,
            self.display_fields,
        )
        object.__setattr__(
            self,
            "display_fields",
            validated_lifeline.display_fields,
        )


@dataclass(frozen=True)
class ChiOperationObservationStep:
    """One live-model transition and its protocol packets.

    A produced packet must later appear as the exact same live object at its
    acceptance step.  This boundary observes one in-memory runtime; it is not
    a correlation adapter for detached or deserialized packet traces.  A
    retained request message object may be reused by protocol Retry within one
    operation, but not as the identity of a new operation generation.
    """

    model_step: int
    label: str
    before: ChiCoherenceState
    after: ChiCoherenceState
    accepted_packet: ChiNetworkPacket | None = None
    produced: tuple[ChiNetworkPacket, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.model_step, int)
            or isinstance(self.model_step, bool)
            or self.model_step < 0
        ):
            raise ValueError("CHI observation model_step must be non-negative")
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("CHI observation step requires a label")
        if not isinstance(self.before, ChiCoherenceState) or not isinstance(
            self.after, ChiCoherenceState
        ):
            raise TypeError(
                "CHI observation step requires coherence before/after states"
            )
        if (
            self.accepted_packet is not None
            and not isinstance(self.accepted_packet, ChiNetworkPacket)
        ):
            raise TypeError("accepted_packet must be a CHI network packet")
        produced = tuple(self.produced)
        if any(not isinstance(item, ChiNetworkPacket) for item in produced):
            raise TypeError("produced must contain CHI network packets")
        object.__setattr__(self, "produced", produced)


def _coherence_state(value: object) -> ChiCoherenceState:
    if isinstance(value, ChiCoherenceNetworkState):
        return value.coherence
    if isinstance(value, ChiCoherenceState):
        return value
    raise TypeError("CHI flow observation requires a coherence runtime state")


def chi_network_observation_steps(
    emissions: Sequence[ChiCoherenceNetworkEvent],
    state_history: Sequence[ChiCoherenceNetworkState],
) -> tuple[ChiOperationObservationStep, ...]:
    """Retain protocol transition points from one network-scheduled run."""

    events = tuple(emissions)
    history = tuple(state_history)
    if any(not isinstance(item, ChiCoherenceNetworkEvent) for item in events):
        raise TypeError("network observation requires coherence-network events")
    if len(history) != len(events) + 1:
        raise ValueError(
            "network state history must contain one state around each event"
        )
    if any(not isinstance(item, ChiCoherenceNetworkState) for item in history):
        raise TypeError(
            "network observation requires coherence-network state history"
        )

    retained: list[ChiOperationObservationStep] = []
    relevant_kinds = frozenset(
        (
            ChiCoherenceNetworkEventKind.ISSUE,
            ChiCoherenceNetworkEventKind.PROTOCOL_CREDIT,
            ChiCoherenceNetworkEventKind.RETRY,
            ChiCoherenceNetworkEventKind.LOCAL_WRITE,
            ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT,
        )
    )
    for index, event in enumerate(events):
        before = history[index].coherence
        after = history[index + 1].coherence
        if event.kind not in relevant_kinds:
            if before != after:
                raise ValueError(
                    "a filtered network move changed CHI coherence state"
                )
            continue
        packet = (
            event.packet
            if event.kind is ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT
            else None
        )
        opcode = _message_name(event.packet) if event.packet is not None else ""
        kind_label = {
            ChiCoherenceNetworkEventKind.ISSUE: "local request issue",
            ChiCoherenceNetworkEventKind.PROTOCOL_CREDIT: (
                "Home P-Credit grant"
            ),
            ChiCoherenceNetworkEventKind.RETRY: "credited request reissue",
            ChiCoherenceNetworkEventKind.LOCAL_WRITE: "RN-local write",
            ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT: (
                f"{event.participant} accepts {opcode}"
            ),
        }[event.kind]
        retained.append(
            ChiOperationObservationStep(
                model_step=index,
                label=kind_label,
                before=before,
                after=after,
                accepted_packet=packet,
                produced=event.produced,
            )
        )
    return tuple(retained)


def chi_network_flow_participants(
    session: ChiCoherenceNetworkSession,
) -> tuple[ChiFlowParticipant, ...]:
    """Project resolved requester/Home/Snoopee roles into lifelines."""

    if not isinstance(session, ChiCoherenceNetworkSession):
        raise TypeError("CHI participant projection requires a network session")
    resolved = session.resolved
    requesters = resolved.role_bindings("requester")
    home = resolved.role_binding("home")
    try:
        snoopees = resolved.role_bindings("snoopee")
    except KeyError:
        snoopees = ()
    role_order = ("requester", "home", "snoopee")
    role_by_name: dict[str, set[str]] = {}
    ordered_bindings = (
        *requesters,
        home,
        *snoopees,
    )
    for role, bindings in (
        ("requester", requesters),
        ("home", (home,)),
        ("snoopee", snoopees),
    ):
        for binding in bindings:
            role_by_name.setdefault(binding.name, set()).add(role)
    participants = []
    seen: set[int] = set()
    for binding in ordered_bindings:
        if len(binding.node_ids) != 1:
            raise ValueError(
                "one CHI flow lifeline requires exactly one NodeID"
            )
        node_id = next(iter(binding.node_ids))
        if node_id in seen:
            continue
        seen.add(node_id)
        role = "/".join(
            item
            for item in role_order
            if item in role_by_name[binding.name]
        )
        participants.append(
            ChiFlowParticipant(
                node_id,
                binding.name,
                f"{binding.name.upper()} · {role}",
                role,
                {
                    "NodeID": f"0x{node_id:x}",
                },
            )
        )
    return tuple(participants)


def _message_name(packet: ChiNetworkPacket | None) -> str:
    if packet is None:
        return ""
    name = type(packet.message).__name__
    if name.startswith("Chi"):
        name = name[3:]
    if name.endswith("Message"):
        name = name[:-7]
    return name


def _message_fields(packet: ChiNetworkPacket) -> dict[str, object]:
    message = packet.message
    fields: dict[str, object] = {}
    transaction_id = getattr(message, "transaction_id", None)
    if isinstance(transaction_id, int):
        fields["TxnID"] = f"0x{transaction_id:x}"
    address = getattr(message, "address", None)
    if isinstance(address, int):
        fields["address"] = f"0x{address:x}"
    data_buffer_id = getattr(message, "data_buffer_id", None)
    if isinstance(data_buffer_id, int):
        fields["DBID"] = f"0x{data_buffer_id:x}"
    response = getattr(message, "response", None)
    if response is not None:
        fields["Resp"] = getattr(response, "name", str(response))
    if hasattr(message, "allow_retry"):
        fields["AllowRetry"] = bool(message.allow_retry)
    protocol_credit_type = getattr(message, "protocol_credit_type", None)
    if isinstance(protocol_credit_type, int):
        fields["PCrdType"] = protocol_credit_type
    if isinstance(message, ChiCopyBackWrDataMessage):
        fields["ByteEnable"] = {
            0: "zero",
            (1 << 64) - 1: "full-line",
        }.get(message.byte_enable, "partial")
        fields["Data"] = "zero" if message.data == 0 else "present"
    summary = []
    for key, short_key in (
        ("TxnID", "T"),
        ("DBID", "D"),
        ("Resp", "R"),
    ):
        if key not in fields:
            continue
        rendered = str(fields[key])
        if rendered.startswith("0x"):
            rendered = rendered[2:]
        summary.append(f"{short_key}{rendered}")
    if fields.get("PCrdType") not in (None, 0):
        summary.append(f"P{fields['PCrdType']}")
    if "AllowRetry" in fields:
        summary.append(f"AR{int(bool(fields['AllowRetry']))}")
    if isinstance(message, ChiCopyBackWrDataMessage):
        summary.append(
            "BE0" if fields["ByteEnable"] == "zero" else "BEfull"
        )
    fields["summary"] = " ".join(summary)
    return fields


def _hex_ids(values: Sequence[int]) -> str:
    return ",".join(f"0x{item:x}" for item in sorted(values)) or "-"


def _request_address(value: object) -> int | None:
    request = getattr(value, "request", value)
    address = getattr(request, "address", None)
    return address if isinstance(address, int) else None


def _rn_state_label(
    state: ChiCoherenceState,
    node_id: int,
    address: int,
) -> str:
    rn = state.request_nodes[node_id]
    line = rn.line_at(address)
    line_state = "-" if line is None else line.state.value
    pending = tuple(
        transaction_id
        for transaction_id, request in rn.pending_transactions.items()
        if request.address == address
    )
    copybacks = tuple(
        (
            transaction_id,
            getattr(getattr(item, "outcome", None), "value", "pending"),
        )
        for transaction_id, item in rn.pending_copybacks.items()
        if _request_address(item) == address
    )
    retry_phases = tuple(
        (
            transaction_id,
            getattr(entry.phase, "value", str(entry.phase)),
        )
        for transaction_id, entry in rn.request_retry.entries.items()
        if getattr(entry.original_request, "address", None) == address
    )
    copyback_text = ",".join(
        f"0x{transaction_id:x}:{outcome}"
        for transaction_id, outcome in copybacks
    ) or "-"
    retry_text = ",".join(
        f"0x{transaction_id:x}:{phase}"
        for transaction_id, phase in retry_phases
    ) or "-"
    return (
        f"line={line_state} | txn={_hex_ids(pending)} | "
        f"copyback={copyback_text} | retry={retry_text}"
    )


def _home_state_label(state: ChiCoherenceState, address: int) -> str:
    home = state.home
    entry = home.directory.get(address)
    if entry is None:
        directory = "dir=-"
    else:
        unique = (
            "-" if entry.unique_owner is None else f"0x{entry.unique_owner:x}"
        )
        dirty = (
            "-"
            if entry.shared_dirty_owner is None
            else f"0x{entry.shared_dirty_owner:x}"
        )
        directory = (
            f"dir[U={unique};S={_hex_ids(tuple(entry.sharers))};SD={dirty}]"
        )
    pending = tuple(
        data_buffer_id
        for data_buffer_id, item in home.pending.items()
        if item.request.address == address
    )
    copybacks = tuple(
        data_buffer_id
        for data_buffer_id, item in home.pending_copybacks.items()
        if _request_address(item) == address
    )
    backing = home.backing.line_at(address)
    backing_text = "-" if backing is None else f"v{backing.version}"
    retry = home.request_retry
    return (
        f"{directory} | pending={_hex_ids(pending)} | "
        f"copyback={_hex_ids(copybacks)} | backing={backing_text} | "
        f"retry_debt={len(retry.retry_debts)} "
        f"reserved={retry.reserved_count}"
    )


def _state_label(
    state: ChiCoherenceState,
    participant: ChiFlowParticipant,
    address: int,
) -> str:
    if participant.role == "home":
        return _home_state_label(state, address)
    if participant.node_id not in state.request_nodes:
        return "outside selected coherence state"
    return _rn_state_label(state, participant.node_id, address)


def _short_state_label(
    state: ChiCoherenceState,
    participant: ChiFlowParticipant,
    address: int,
) -> str:
    if participant.role == "home":
        home = state.home
        entry = home.directory.get(address)
        if entry is None:
            directory = "D:-"
        elif entry.unique_owner is not None:
            directory = f"D:U{entry.unique_owner:x}"
        elif entry.sharers:
            directory = "D:S" + ",".join(
                f"{item:x}" for item in sorted(entry.sharers)
            )
            if entry.shared_dirty_owner is not None:
                directory += f"/SD{entry.shared_dirty_owner:x}"
        else:
            directory = "D:I"
        pending = sum(
            item.request.address == address
            for item in home.pending.values()
        )
        copybacks = sum(
            _request_address(item) == address
            for item in home.pending_copybacks.values()
        )
        backing = home.backing.line_at(address)
        suffix = []
        if pending:
            suffix.append(f"P{pending}")
        if copybacks:
            suffix.append(f"CB{copybacks}")
        if home.request_retry.retry_debts:
            suffix.append(f"RD{len(home.request_retry.retry_debts)}")
        if home.request_retry.reserved_count:
            suffix.append(f"PR{home.request_retry.reserved_count}")
        if backing is not None:
            suffix.append(f"Bv{backing.version}")
        return " ".join((directory, *suffix))

    rn = state.request_nodes[participant.node_id]
    line = rn.line_at(address)
    summary = "-" if line is None else line.state.value
    pending = tuple(
        transaction_id
        for transaction_id, request in rn.pending_transactions.items()
        if request.address == address
    )
    copybacks = tuple(
        (
            transaction_id,
            getattr(getattr(item, "outcome", None), "value", "pending"),
        )
        for transaction_id, item in rn.pending_copybacks.items()
        if _request_address(item) == address
    )
    retry = tuple(
        (
            transaction_id,
            getattr(entry.phase, "value", str(entry.phase)),
        )
        for transaction_id, entry in rn.request_retry.entries.items()
        if getattr(entry.original_request, "address", None) == address
    )
    phase_abbreviation = {
        "initial_in_flight": "init",
        "wait_retry_credit": "wait-credit",
        "retried_in_flight": "retry-flight",
        "live_unissued_data": "live",
        "live_ud": "live",
        "canceled_invalid": "cancel",
        "canceled_i": "cancel",
    }
    suffix = [f"T{item:x}" for item in pending]
    suffix.extend(
        f"CB{transaction_id:x}:"
        f"{phase_abbreviation.get(outcome, outcome.replace('_', '-'))}"
        for transaction_id, outcome in copybacks
    )
    suffix.extend(
        f"R{transaction_id:x}:"
        f"{phase_abbreviation.get(phase, phase.replace('_', '-'))}"
        for transaction_id, phase in retry
    )
    return " ".join((summary, *suffix))


def _root_operation_ref(
    packet: ChiNetworkPacket,
    prefix: str,
    generation: int,
) -> str:
    if packet.channel is not ChiChannelKind.REQ:
        raise ValueError(
            "a protocol packet without a producing message must be a REQ root"
        )
    transaction_id = getattr(packet.message, "transaction_id", None)
    if not isinstance(transaction_id, int):
        raise ValueError("CHI root request requires a transaction identifier")
    base = (
        f"{prefix}:n{packet.source_id:x}:h{packet.target_id:x}:"
        f"t{transaction_id:x}"
    )
    return base if generation == 0 else f"{base}:g{generation}"


def _request_identity(packet: ChiNetworkPacket) -> tuple[int, int, int]:
    if packet.channel is not ChiChannelKind.REQ:
        raise ValueError("CHI request identity requires a REQ packet")
    transaction_id = getattr(packet.message, "transaction_id", None)
    if not isinstance(transaction_id, int):
        raise ValueError("CHI request identity requires a TxnID")
    return packet.source_id, packet.target_id, transaction_id


def _packet_operations(
    steps: Sequence[ChiOperationObservationStep],
    prefix: str,
) -> dict[int, str]:
    operations: dict[int, str] = {}
    root_generations: dict[tuple[int, int, int], int] = {}
    retry_operation_by_request: dict[tuple[int, int, int], str] = {}
    retry_request_by_credit: dict[
        tuple[int, int, int], tuple[int, int, int]
    ] = {}
    registered_retry_packets: set[int] = set()

    def new_root(packet: ChiNetworkPacket) -> str:
        key = _request_identity(packet)
        generation = root_generations.get(key, 0)
        root_generations[key] = generation + 1
        return _root_operation_ref(packet, prefix, generation)

    def register_retry(
        packet: ChiNetworkPacket,
        operation: str,
    ) -> None:
        message = packet.message
        if not isinstance(message, ChiRetryAckMessage):
            raise TypeError("retry registration requires RetryAck")
        request_key = (
            packet.target_id,
            packet.source_id,
            message.transaction_id,
        )
        previous_operation = retry_operation_by_request.get(request_key)
        if (
            previous_operation is not None
            and previous_operation != operation
        ):
            raise ValueError(
                "two retry operations reuse one requester/Home/TxnID"
            )
        credit_key = (
            packet.source_id,
            packet.target_id,
            message.protocol_credit_type,
        )
        previous_request = retry_request_by_credit.get(credit_key)
        if previous_request is not None and previous_request != request_key:
            raise ValueError(
                "concurrent same-type P-Credit needs explicit grant lineage"
            )
        retry_operation_by_request[request_key] = operation
        retry_request_by_credit[credit_key] = request_key
        registered_retry_packets.add(id(packet))

    for step in steps:
        accepted = step.accepted_packet
        accepted_operation = (
            operations.get(id(accepted)) if accepted is not None else None
        )
        if accepted is not None and accepted_operation is None:
            if accepted.channel is ChiChannelKind.REQ:
                accepted_operation = retry_operation_by_request.pop(
                    _request_identity(accepted),
                    None,
                )
            if accepted_operation is None:
                accepted_operation = new_root(accepted)
            operations[id(accepted)] = accepted_operation
        if isinstance(
            getattr(accepted, "message", None),
            ChiRetryAckMessage,
        ) and id(accepted) not in registered_retry_packets:
            assert accepted_operation is not None
            register_retry(accepted, accepted_operation)
        for packet in step.produced:
            operation = accepted_operation
            if operation is None and packet.channel is ChiChannelKind.REQ:
                operation = retry_operation_by_request.pop(
                    _request_identity(packet),
                    None,
                )
                if operation is None:
                    operation = new_root(packet)
            if operation is None and isinstance(
                packet.message, ChiPCrdGrantMessage
            ):
                credit_key = (
                    packet.source_id,
                    packet.target_id,
                    packet.message.protocol_credit_type,
                )
                request_key = retry_request_by_credit.pop(
                    credit_key,
                    None,
                )
                if request_key is not None:
                    operation = retry_operation_by_request.get(request_key)
            if operation is None:
                raise ValueError(
                    f"cannot correlate produced {_message_name(packet)} "
                    "to an observed operation"
                )
            previous = operations.get(id(packet))
            if previous is not None and previous != operation:
                raise ValueError("one CHI packet was assigned to two operations")
            operations[id(packet)] = operation
            if isinstance(packet.message, ChiRetryAckMessage):
                if id(packet) not in registered_retry_packets:
                    register_retry(packet, operation)
    return operations


def project_chi_transaction_flow(
    *,
    name: str,
    operation_prefix: str,
    address: int,
    participants: Sequence[ChiFlowParticipant],
    steps: Sequence[ChiOperationObservationStep],
) -> TransactionTimeSpaceView:
    """Build shared-reference views from one live CHI runtime.

    Produced-to-accepted lineage is checked by object identity.  Callers with
    serialized or otherwise detached traces need an explicit trace identity
    contract before using this projector.  Distinct operation generations
    likewise require distinct live request message objects.
    """

    if not isinstance(name, str) or not name:
        raise ValueError("CHI transaction flow requires a name")
    if not isinstance(operation_prefix, str) or not operation_prefix:
        raise ValueError("CHI transaction flow requires an operation prefix")
    if (
        not isinstance(address, int)
        or isinstance(address, bool)
        or address < 0
    ):
        raise ValueError("CHI transaction flow requires an address")
    participant_items = tuple(participants)
    step_items = tuple(steps)
    if not participant_items or any(
        not isinstance(item, ChiFlowParticipant)
        for item in participant_items
    ):
        raise TypeError("CHI transaction flow requires typed participants")
    if not step_items or any(
        not isinstance(item, ChiOperationObservationStep)
        for item in step_items
    ):
        raise TypeError("CHI transaction flow requires typed steps")
    if tuple(sorted(item.model_step for item in step_items)) != tuple(
        item.model_step for item in step_items
    ):
        raise ValueError("CHI observation steps must be in model-step order")
    refs = tuple(item.ref for item in participant_items)
    node_ids = tuple(item.node_id for item in participant_items)
    if len(set(refs)) != len(refs) or len(set(node_ids)) != len(node_ids):
        raise ValueError("CHI flow participants must have unique refs/NodeIDs")
    participant_by_node = {
        item.node_id: item for item in participant_items
    }

    accepted_steps = tuple(
        step for step in step_items if step.accepted_packet is not None
    )
    accepted_ids = {id(step.accepted_packet) for step in accepted_steps}
    missing_deliveries = {
        id(packet)
        for step in step_items
        for packet in step.produced
        if id(packet) not in accepted_ids
    }
    if missing_deliveries:
        raise ValueError(
            "CHI flow projection requires every produced packet to be "
            "accepted as the same live packet object"
        )
    operations = _packet_operations(step_items, operation_prefix)

    messages: list[TimeSpaceMessage] = []
    event_by_packet_id: dict[int, str] = {}
    step_by_packet_id: dict[int, ChiOperationObservationStep] = {}
    for index, step in enumerate(accepted_steps):
        packet = step.accepted_packet
        assert packet is not None
        try:
            source = participant_by_node[packet.source_id].ref
            destination = participant_by_node[packet.target_id].ref
        except KeyError as error:
            raise ValueError(
                "accepted CHI packet references an undeclared participant"
            ) from error
        event_ref = f"{operation_prefix}:message:{index:02d}"
        event_by_packet_id[id(packet)] = event_ref
        step_by_packet_id[id(packet)] = step
        messages.append(
            TimeSpaceMessage(
                event_ref=event_ref,
                operation_ref=operations[id(packet)],
                source=source,
                destination=destination,
                time=step.model_step,
                label=_message_name(packet),
                lane=packet.channel.value.lower(),
                channel=packet.channel.value,
                display_fields=_message_fields(packet),
                observation_point=MessageObservationPoint.ACCEPTANCE,
            )
        )

    state_changes: list[TimeSpaceStateChange] = []
    state_refs_by_step: dict[
        int, dict[int, str]
    ] = {}
    for step in step_items:
        accepted_operation = (
            operations.get(id(step.accepted_packet))
            if step.accepted_packet is not None
            else None
        )
        produced_operations = {
            operations[id(packet)] for packet in step.produced
        }
        state_operation = accepted_operation or (
            next(iter(produced_operations))
            if len(produced_operations) == 1
            else f"{operation_prefix}:system"
        )
        for participant in participant_items:
            before = _state_label(step.before, participant, address)
            after = _state_label(step.after, participant, address)
            if before == after:
                continue
            short_before = _short_state_label(
                step.before,
                participant,
                address,
            )
            short_after = _short_state_label(
                step.after,
                participant,
                address,
            )
            event_ref = (
                f"{operation_prefix}:state:{step.model_step:03d}:"
                f"{participant.ref}"
            )
            state_refs_by_step.setdefault(step.model_step, {})[
                participant.node_id
            ] = event_ref
            state_changes.append(
                TimeSpaceStateChange(
                    event_ref=event_ref,
                    operation_ref=state_operation,
                    lifeline=participant.ref,
                    time=step.model_step,
                    before=before,
                    after=after,
                    label="coherence/transaction state",
                    display_fields={
                        "badge": short_after,
                        "summary": (
                            f"{participant.ref}: "
                            f"{short_before} → {short_after}"
                        ),
                        "transition": step.label,
                    },
                )
            )

    causal: dict[tuple[str, str], str] = {}

    def add_cause(source: str, destination: str, reason: str) -> None:
        if source == destination:
            return
        causal[(source, destination)] = reason

    for step in step_items:
        accepted = step.accepted_packet
        accepted_ref = (
            event_by_packet_id.get(id(accepted))
            if accepted is not None
            else None
        )
        changed = state_refs_by_step.get(step.model_step, {})
        for packet in step.produced:
            destination_ref = event_by_packet_id[id(packet)]
            if accepted_ref is not None:
                add_cause(
                    accepted_ref,
                    destination_ref,
                    "participant emits",
                )
                continue
            source_state = changed.get(packet.source_id)
            if source_state is not None:
                add_cause(
                    source_state,
                    destination_ref,
                    "local issue emits",
                )

    packet_by_ref = {
        event_by_packet_id[id(step.accepted_packet)]: step.accepted_packet
        for step in accepted_steps
        if step.accepted_packet is not None
    }
    snoop_join_responses: dict[
        tuple[str, int, int, int], list[str]
    ] = {}
    for step in step_items:
        response_packet = step.accepted_packet
        if response_packet is None or not isinstance(
            response_packet.message,
            (ChiSnpRespMessage, ChiSnpRespDataMessage),
        ):
            continue
        response = response_packet.message
        matching_before = tuple(
            (data_buffer_id, pending)
            for data_buffer_id, pending in step.before.home.pending.items()
            if (
                pending.snoop_transaction_id == response.transaction_id
                and response_packet.source_id in pending.snoop_targets
            )
        )
        if len(matching_before) != 1:
            continue
        data_buffer_id, pending_before = matching_before[0]
        pending_after = step.after.home.pending.get(data_buffer_id)
        if (
            pending_after is None
            or pending_before.completion_sent
            or response_packet.source_id in pending_before.snoop_results
            or response_packet.source_id
            not in pending_after.snoop_results
        ):
            continue
        join_key = (
            operations[id(response_packet)],
            response_packet.target_id,
            response.transaction_id,
            data_buffer_id,
        )
        response_refs = snoop_join_responses.setdefault(join_key, [])
        response_refs.append(event_by_packet_id[id(response_packet)])
        if (
            not pending_after.completion_sent
            or not pending_after.all_snoops_complete
        ):
            continue
        completion_packets = tuple(
            packet
            for packet in step.produced
            if (
                isinstance(
                    packet.message,
                    (ChiCompMessage, ChiCompDataMessage),
                )
                and packet.source_id == response_packet.target_id
                and packet.target_id == pending_before.requester_id
                and operations[id(packet)]
                == operations[id(response_packet)]
            )
        )
        for completion_packet in completion_packets:
            completion_ref = event_by_packet_id[id(completion_packet)]
            for response_ref in response_refs:
                add_cause(
                    response_ref,
                    completion_ref,
                    "Home Snoop-response join",
                )

    retry_acks = tuple(
        (event_ref, packet)
        for event_ref, packet in packet_by_ref.items()
        if isinstance(packet.message, ChiRetryAckMessage)
    )
    grants = tuple(
        (event_ref, packet)
        for event_ref, packet in packet_by_ref.items()
        if isinstance(packet.message, ChiPCrdGrantMessage)
    )
    for retry_ref, retry_packet in retry_acks:
        for grant_ref, grant_packet in grants:
            if (
                retry_packet.message.protocol_credit_type
                == grant_packet.message.protocol_credit_type
                and operations[id(retry_packet)]
                == operations[id(grant_packet)]
                and retry_packet.source_id == grant_packet.source_id
                and retry_packet.target_id == grant_packet.target_id
            ):
                retry_producer = next(
                    (
                        step
                        for step in step_items
                        if any(
                            packet is retry_packet
                            for packet in step.produced
                        )
                    ),
                    None,
                )
                grant_producer = next(
                    (
                        step
                        for step in step_items
                        if any(
                            packet is grant_packet
                            for packet in step.produced
                        )
                    ),
                    None,
                )
                if (
                    retry_producer is not None
                    and retry_producer.accepted_packet is not None
                    and grant_producer is not None
                ):
                    grant_state = state_refs_by_step.get(
                        grant_producer.model_step, {}
                    ).get(grant_packet.source_id)
                    if grant_state is not None:
                        add_cause(
                            event_by_packet_id[
                                id(retry_producer.accepted_packet)
                            ],
                            grant_state,
                            "Retry debt enables P-Credit",
                        )
                later_requests = tuple(
                    (event_ref, packet)
                    for event_ref, packet in packet_by_ref.items()
                    if (
                        packet.channel is ChiChannelKind.REQ
                        and operations[id(packet)] == operations[id(grant_packet)]
                        and packet.source_id == retry_packet.target_id
                        and packet.target_id == retry_packet.source_id
                        and getattr(
                            packet.message,
                            "transaction_id",
                            None,
                        )
                        == retry_packet.message.transaction_id
                        and step_by_packet_id[id(packet)].model_step
                        > step_by_packet_id[id(grant_packet)].model_step
                    )
                )
                for request_ref, _request in later_requests:
                    add_cause(
                        retry_ref,
                        request_ref,
                        "RetryAck observed",
                    )
                    add_cause(
                        grant_ref,
                        request_ref,
                        "P-Credit enables reissue",
                    )

    request_operation_by_message_id: dict[int, str] = {}
    for step in step_items:
        packets = (
            ((step.accepted_packet,) if step.accepted_packet is not None else ())
            + step.produced
        )
        for packet in packets:
            if packet.channel is not ChiChannelKind.REQ:
                continue
            message_id = id(packet.message)
            operation = operations[id(packet)]
            previous = request_operation_by_message_id.get(message_id)
            if previous is not None and previous != operation:
                raise ValueError(
                    "one live CHI request message object cannot identify "
                    "two operation generations"
                )
            request_operation_by_message_id[message_id] = operation
    canceled_copybacks: dict[
        tuple[str, int, int, int], list[tuple[str, int]]
    ] = {}
    for step in step_items:
        snoop = step.accepted_packet
        if (
            snoop is None
            or not isinstance(snoop.message, ChiSnpCleanInvalidMessage)
            or snoop.message.address != address
            or snoop.target_id not in step.before.request_nodes
            or snoop.target_id not in step.after.request_nodes
        ):
            continue
        before_pending = step.before.request_nodes[
            snoop.target_id
        ].pending_copybacks
        after_pending = step.after.request_nodes[
            snoop.target_id
        ].pending_copybacks
        canceled_state = state_refs_by_step.get(
            step.model_step,
            {},
        ).get(snoop.target_id)
        if canceled_state is None:
            continue
        for transaction_id, pending_before in before_pending.items():
            pending_after = after_pending.get(transaction_id)
            copyback_operation = request_operation_by_message_id.get(
                id(pending_before.request)
            )
            if (
                copyback_operation is not None
                and _request_address(pending_before) == address
                and pending_before.outcome
                is not ChiRnCopyBackOutcome.CANCELED_I
                and pending_after is not None
                and _request_address(pending_after) == address
                and pending_after.outcome
                is ChiRnCopyBackOutcome.CANCELED_I
            ):
                canceled_copybacks.setdefault(
                    (
                        copyback_operation,
                        snoop.source_id,
                        snoop.target_id,
                        transaction_id,
                    ),
                    [],
                ).append((canceled_state, step.model_step))

    for response_ref, response in packet_by_ref.items():
        if not isinstance(response.message, ChiCompDBIDRespMessage):
            continue
        cancellations = canceled_copybacks.get(
            (
                operations[id(response)],
                response.source_id,
                response.target_id,
                response.message.transaction_id,
            ),
            (),
        )
        response_step = step_by_packet_id[id(response)].model_step
        preceding = tuple(
            cancellation
            for cancellation in cancellations
            if cancellation[1] < response_step
        )
        if not preceding:
            continue
        canceled_state, _canceled_step = max(
            preceding,
            key=lambda item: item[1],
        )
        add_cause(
            canceled_state,
            response_ref,
            "same-line cancel selects response",
        )

    return TransactionTimeSpaceView(
        name=name,
        lifelines=tuple(
            TimeSpaceLifeline(
                participant.ref,
                participant.label,
                participant.role,
                participant.display_fields,
            )
            for participant in participant_items
        ),
        messages=tuple(messages),
        state_changes=tuple(state_changes),
        causal_edges=tuple(
            TimeSpaceCausalEdge(source, destination, reason)
            for (source, destination), reason in causal.items()
        ),
        time_basis=TimeBasis.MODEL_STEP,
        scope=ViewScope.SCENARIO,
        evidence_basis=EvidenceBasis.OBSERVED,
    )


__all__ = [
    "ChiFlowParticipant",
    "ChiOperationObservationStep",
    "chi_network_flow_participants",
    "chi_network_observation_steps",
    "project_chi_transaction_flow",
]
