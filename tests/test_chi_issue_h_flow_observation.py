from __future__ import annotations

from dataclasses import replace
import unittest

from protocol_model.protocols.amba.chi.issue_h.observation import (
    ChiFlowParticipant,
    ChiOperationObservationStep,
    chi_network_flow_participants,
    chi_network_observation_steps,
    project_chi_transaction_flow,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiCompDBIDRespMessage,
    ChiEvictMessage,
    ChiNetworkPacket,
    ChiRetryAckMessage,
    ChiWriteBackFullMessage,
)
from showcase.demos.chi.issue_h_flow_gallery.coherence_cases import (
    ADDRESS,
    run_clean_read_unique_fanout,
)
from showcase.demos.chi.issue_h_flow_gallery.progress_cases import (
    CONTENDER_NODE_ID,
    HOME_NODE_ID,
    LINE_ADDRESS,
    run_clean_evict_retry,
    run_writeback_snoop_cancellation,
)


def _writeback_steps(case) -> tuple[ChiOperationObservationStep, ...]:
    return chi_network_observation_steps(
        case.emissions,
        case.state_history,
    )


def _clone_packet_sequence(
    steps: tuple[ChiOperationObservationStep, ...],
    *,
    model_step_offset: int,
) -> tuple[ChiOperationObservationStep, ...]:
    packets: dict[int, ChiNetworkPacket] = {}
    messages: dict[int, object] = {}

    def clone(packet: ChiNetworkPacket | None) -> ChiNetworkPacket | None:
        if packet is None:
            return None
        packet_id = id(packet)
        if packet_id not in packets:
            message_id = id(packet.message)
            if message_id not in messages:
                messages[message_id] = replace(packet.message)
            packets[packet_id] = replace(
                packet,
                message=messages[message_id],
            )
        return packets[packet_id]

    return tuple(
        replace(
            step,
            model_step=step.model_step + model_step_offset,
            accepted_packet=clone(step.accepted_packet),
            produced=tuple(
                clone(packet)
                for packet in step.produced
            ),
        )
        for step in steps
    )


class ChiIssueHFlowObservationTest(unittest.TestCase):
    def test_detached_equal_packet_is_not_live_runtime_lineage(self) -> None:
        case = run_clean_evict_retry()
        steps = list(
            chi_network_observation_steps(
                case.emissions,
                case.state_history,
            )
        )
        request_index = next(
            index
            for index, step in enumerate(steps)
            if (
                step.accepted_packet is not None
                and isinstance(step.accepted_packet.message, ChiEvictMessage)
            )
        )
        accepted = steps[request_index].accepted_packet
        assert accepted is not None
        detached_equal_packet = replace(accepted)
        self.assertEqual(accepted, detached_equal_packet)
        self.assertIsNot(accepted, detached_equal_packet)
        steps[request_index] = replace(
            steps[request_index],
            accepted_packet=detached_equal_packet,
        )

        with self.assertRaisesRegex(
            ValueError,
            "accepted as the same live packet object",
        ):
            project_chi_transaction_flow(
                name="detached packet is not live lineage",
                operation_prefix="detached",
                address=LINE_ADDRESS,
                participants=chi_network_flow_participants(case.session),
                steps=steps,
            )

    def test_unrelated_later_dbid_response_does_not_gain_cancel_edge(
        self,
    ) -> None:
        case = run_writeback_snoop_cancellation()
        steps = list(_writeback_steps(case))
        producer_index, response = next(
            (index, packet)
            for index, step in enumerate(steps)
            for packet in step.produced
            if isinstance(packet.message, ChiCompDBIDRespMessage)
        )
        accept_index = next(
            index
            for index, step in enumerate(steps)
            if step.accepted_packet is response
        )
        unrelated_response = replace(
            response,
            target_id=CONTENDER_NODE_ID,
        )
        steps[producer_index] = replace(
            steps[producer_index],
            produced=tuple(
                unrelated_response if packet is response else packet
                for packet in steps[producer_index].produced
            ),
        )
        steps[accept_index] = replace(
            steps[accept_index],
            accepted_packet=unrelated_response,
        )

        view = project_chi_transaction_flow(
            name="different requester DBID response",
            operation_prefix="unrelated-dbid",
            address=LINE_ADDRESS,
            participants=chi_network_flow_participants(case.session),
            steps=steps,
        )

        self.assertFalse(
            tuple(
                edge
                for edge in view.causal_edges
                if edge.reason == "same-line cancel selects response"
            )
        )

    def test_later_copyback_generation_does_not_reuse_old_cancel_edge(
        self,
    ) -> None:
        case = run_writeback_snoop_cancellation()
        steps = list(_writeback_steps(case))
        request = next(
            packet
            for step in steps
            for packet in step.produced
            if isinstance(packet.message, ChiWriteBackFullMessage)
        )
        response = next(
            packet
            for step in steps
            for packet in step.produced
            if isinstance(packet.message, ChiCompDBIDRespMessage)
        )
        second_request = replace(
            request,
            message=replace(request.message),
        )
        second_response = replace(
            response,
            message=replace(response.message),
        )
        final_state = case.final_coherence
        next_step = steps[-1].model_step + 1
        steps.extend(
            (
                ChiOperationObservationStep(
                    next_step,
                    "issue a later same-identity WriteBackFull",
                    final_state,
                    final_state,
                    produced=(second_request,),
                ),
                ChiOperationObservationStep(
                    next_step + 1,
                    "Home accepts later WriteBackFull",
                    final_state,
                    final_state,
                    accepted_packet=second_request,
                    produced=(second_response,),
                ),
                ChiOperationObservationStep(
                    next_step + 2,
                    "requester accepts later DBID response",
                    final_state,
                    final_state,
                    accepted_packet=second_response,
                ),
            )
        )

        view = project_chi_transaction_flow(
            name="later copyback generation",
            operation_prefix="copyback-generation",
            address=LINE_ADDRESS,
            participants=chi_network_flow_participants(case.session),
            steps=steps,
        )

        cancel_edges = tuple(
            edge
            for edge in view.causal_edges
            if edge.reason == "same-line cancel selects response"
        )
        self.assertEqual(1, len(cancel_edges))
        operation_by_event = {
            message.event_ref: message.operation_ref
            for message in view.messages
        }
        self.assertEqual(
            "copyback-generation:n7:h21:t31",
            operation_by_event[cancel_edges[0].destination_event_ref],
        )

    def test_sequential_txnid_reuse_gets_a_new_operation_generation(
        self,
    ) -> None:
        case = run_clean_read_unique_fanout()
        first = chi_network_observation_steps(
            case.emissions,
            case.state_history,
        )
        second = _clone_packet_sequence(
            first,
            model_step_offset=first[-1].model_step + 1,
        )

        view = project_chi_transaction_flow(
            name="sequential TxnID reuse",
            operation_prefix="reuse",
            address=ADDRESS,
            participants=chi_network_flow_participants(case.session),
            steps=(*first, *second),
        )

        self.assertEqual(
            (
                "reuse:n7:h21:t12",
                "reuse:n7:h21:t12:g1",
            ),
            tuple(
                sorted(
                    {
                        message.operation_ref
                        for message in view.messages
                    }
                )
            ),
        )
        operation_by_event = {
            message.event_ref: message.operation_ref
            for message in view.messages
        }
        for edge in view.causal_edges:
            if edge.reason != "Home Snoop-response join":
                continue
            self.assertEqual(
                operation_by_event[edge.source_event_ref],
                operation_by_event[edge.destination_event_ref],
            )

    def test_operation_ref_includes_the_target_home_identity(self) -> None:
        case = run_clean_evict_retry()
        network_steps = chi_network_observation_steps(
            case.emissions,
            case.state_history,
        )
        request = next(
            packet
            for step in network_steps
            for packet in step.produced
            if isinstance(packet.message, ChiEvictMessage)
        )
        second_home_id = HOME_NODE_ID + 1
        state = case.initial_coherence
        participants = (
            *chi_network_flow_participants(case.session),
            ChiFlowParticipant(
                second_home_id,
                "hn1",
                "HN1 · second Home",
                "home",
            ),
        )

        def steps_for(
            second_request: ChiNetworkPacket,
        ) -> tuple[ChiOperationObservationStep, ...]:
            return (
                ChiOperationObservationStep(
                    0,
                    "issue requests to two Home targets",
                    state,
                    state,
                    produced=(request, second_request),
                ),
                ChiOperationObservationStep(
                    1,
                    "first Home accepts",
                    state,
                    state,
                    accepted_packet=request,
                ),
                ChiOperationObservationStep(
                    2,
                    "second Home accepts",
                    state,
                    state,
                    accepted_packet=second_request,
                ),
            )

        reused_message_request = replace(
            request,
            target_id=second_home_id,
        )
        with self.assertRaisesRegex(
            ValueError,
            "request message object cannot identify two operation",
        ):
            project_chi_transaction_flow(
                name="one message object reused across operations",
                operation_prefix="shared-message",
                address=LINE_ADDRESS,
                participants=participants,
                steps=steps_for(reused_message_request),
            )

        second_request = replace(
            reused_message_request,
            message=replace(request.message),
        )
        view = project_chi_transaction_flow(
            name="same TxnID to two Home targets",
            operation_prefix="two-home",
            address=LINE_ADDRESS,
            participants=participants,
            steps=steps_for(second_request),
        )

        self.assertEqual(
            {
                "two-home:n7:h21:t31",
                "two-home:n7:h22:t31",
            },
            {message.operation_ref for message in view.messages},
        )

    def test_concurrent_same_type_retry_credit_requires_grant_lineage(
        self,
    ) -> None:
        case = run_clean_evict_retry()
        all_steps = chi_network_observation_steps(
            case.emissions,
            case.state_history,
        )
        first_issue = next(
            step
            for step in all_steps
            if (
                step.accepted_packet is None
                and any(
                    isinstance(packet.message, ChiEvictMessage)
                    for packet in step.produced
                )
            )
        )
        first_home_retry = next(
            step
            for step in all_steps
            if (
                step.accepted_packet is not None
                and isinstance(
                    step.accepted_packet.message,
                    ChiEvictMessage,
                )
                and any(
                    isinstance(packet.message, ChiRetryAckMessage)
                    for packet in step.produced
                )
            )
        )
        first_retry = first_home_retry.produced[0]
        first_retry_accept = next(
            step
            for step in all_steps
            if step.accepted_packet is first_retry
        )
        first = (
            first_issue,
            first_home_retry,
            first_retry_accept,
        )

        second_txn_id = (
            first_issue.produced[0].message.transaction_id + 1
        )
        second_request = replace(
            first_issue.produced[0],
            message=replace(
                first_issue.produced[0].message,
                transaction_id=second_txn_id,
            ),
        )
        second_retry = replace(
            first_retry,
            message=replace(
                first_retry.message,
                transaction_id=second_txn_id,
            ),
        )
        offset = first_retry_accept.model_step + 1
        second = (
            replace(
                first_issue,
                model_step=first_issue.model_step + offset,
                produced=(second_request,),
            ),
            replace(
                first_home_retry,
                model_step=first_home_retry.model_step + offset,
                accepted_packet=second_request,
                produced=(second_retry,),
            ),
            replace(
                first_retry_accept,
                model_step=first_retry_accept.model_step + offset,
                accepted_packet=second_retry,
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "concurrent same-type P-Credit needs explicit grant lineage",
        ):
            project_chi_transaction_flow(
                name="ambiguous concurrent retry credit",
                operation_prefix="retry-ambiguity",
                address=LINE_ADDRESS,
                participants=chi_network_flow_participants(case.session),
                steps=(*first, *second),
            )


if __name__ == "__main__":
    unittest.main()
