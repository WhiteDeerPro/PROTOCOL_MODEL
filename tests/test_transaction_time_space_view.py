from __future__ import annotations

import json
import unittest

from protocol_model.visualization import (
    TIME_SPACE_VIEW_SCHEMA,
    EvidenceBasis,
    MessageObservationPoint,
    TimeBasis,
    TimeSpaceCausalEdge,
    TimeSpaceLifeline,
    TimeSpaceMessage,
    TimeSpaceStateChange,
    TransactionTimeSpaceView,
    ViewKind,
    transaction_causal_dot,
    transaction_semantic_wavejson,
    transaction_time_space_dot,
)


def _view(
    *,
    time_basis: TimeBasis = TimeBasis.EVENT_INDEX,
) -> TransactionTimeSpaceView:
    return TransactionTimeSpaceView(
        name="one transaction",
        lifelines=(
            TimeSpaceLifeline("requester", "Requester", "endpoint"),
            TimeSpaceLifeline("home", "Home", "authority"),
            TimeSpaceLifeline("memory", "Memory", "backing"),
        ),
        messages=(
            TimeSpaceMessage(
                event_ref="req",
                operation_ref="op-7",
                source="requester",
                destination="home",
                time=0,
                label="request",
                lane="request",
                channel="REQ",
                display_fields={"address": "0x1000", "tags": ["read"]},
            ),
            TimeSpaceMessage(
                event_ref="lookup",
                operation_ref="op-7",
                source="home",
                destination="memory",
                time=1,
                label="lookup",
                channel="MEM",
            ),
            TimeSpaceMessage(
                event_ref="rsp",
                operation_ref="op-7",
                source="home",
                destination="requester",
                time=3,
                label="response",
                lane="response",
                channel="RSP",
            ),
        ),
        state_changes=(
            TimeSpaceStateChange(
                event_ref="state",
                operation_ref="op-7",
                lifeline="home",
                time=2,
                before="pending",
                after="complete",
                label="operation state",
            ),
        ),
        causal_edges=(
            TimeSpaceCausalEdge("req", "lookup", "request accepted"),
            TimeSpaceCausalEdge("lookup", "state", "backing result"),
            TimeSpaceCausalEdge("state", "rsp", "completion emitted"),
        ),
        time_basis=time_basis,
        evidence_basis=EvidenceBasis.OBSERVED,
    )


class TransactionTimeSpaceViewTest(unittest.TestCase):
    def test_view_is_immutable_and_exports_detached_json_data(self) -> None:
        view = _view()

        with self.assertRaises(TypeError):
            view.messages[0].display_fields["address"] = "0x2000"
        with self.assertRaises(TypeError):
            view.messages[0].display_fields["new"] = "value"

        exported = view.to_dict()
        exported["messages"][0]["display_fields"]["address"] = "changed"

        self.assertEqual(TIME_SPACE_VIEW_SCHEMA, exported["schema"])
        self.assertEqual(
            "0x1000",
            view.messages[0].display_fields["address"],
        )
        self.assertEqual(
            "event_index",
            exported["descriptor"]["time_basis"],
        )
        self.assertEqual(
            "transaction_sequence",
            exported["descriptor"]["view_kind"],
        )
        json.dumps(exported)

    def test_descriptor_selects_supported_rendering_kinds(self) -> None:
        view = _view(time_basis=TimeBasis.MODEL_STEP)

        descriptor = view.descriptor(view_kind=ViewKind.CAUSAL_GRAPH)

        self.assertEqual(ViewKind.CAUSAL_GRAPH, descriptor.view_kind)
        self.assertEqual(TimeBasis.MODEL_STEP, descriptor.time_basis)
        self.assertEqual(TIME_SPACE_VIEW_SCHEMA, descriptor.source_schema)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            view.descriptor(view_kind=ViewKind.TOPOLOGY)

    def test_renderers_preserve_explicit_events_and_boundaries(self) -> None:
        view = _view()

        time_space = transaction_time_space_dot(view)
        causality = transaction_causal_dot(view)
        timeline = transaction_semantic_wavejson(view)

        self.assertIn("transaction time-space", time_space)
        self.assertIn("point_0_0 -> point_1_0", time_space)
        self.assertIn("splines=line", time_space)
        self.assertIn('group="lifeline_0"', time_space)
        self.assertIn(
            (
                "lifeline_0 -> point_0_0 -> point_0_1 -> "
                "point_0_2 -> point_0_3"
            ),
            time_space,
        )
        self.assertIn(
            'arrowhead=none, style=dashed, color="#94a3b8"',
            time_space,
        )
        self.assertIn("REQ", time_space)
        self.assertIn("not pins, cycles, or RTL timing", time_space)
        self.assertEqual(3, causality.count(" -> event_"))
        self.assertIn("request accepted", causality)
        self.assertNotIn("time proximity ->", causality)
        self.assertIn("SEMANTIC EVENTS ONLY", timeline["foot"]["text"])
        self.assertIn("NOT PINS/CYCLES/RTL", timeline["foot"]["text"])
        self.assertEqual("EVENT INDEX", timeline["signal"][0]["name"])
        requester_group = timeline["signal"][1]
        self.assertEqual("Requester (requester)", requester_group[0])
        self.assertEqual("REQ · request / tx", requester_group[1]["name"])
        json.dumps(timeline)

    def test_message_observation_point_is_normalized_and_serialized(
        self,
    ) -> None:
        view = TransactionTimeSpaceView(
            name="observation points",
            lifelines=(
                TimeSpaceLifeline("requester", "Requester"),
                TimeSpaceLifeline("home", "Home"),
            ),
            messages=(
                TimeSpaceMessage(
                    "exchange",
                    "op",
                    "requester",
                    "home",
                    0,
                    "issued request",
                ),
                TimeSpaceMessage(
                    "accepted",
                    "op",
                    "home",
                    "requester",
                    1,
                    "accepted response",
                    observation_point="acceptance",
                ),
            ),
        )

        self.assertIs(
            MessageObservationPoint.EXCHANGE,
            view.messages[0].observation_point,
        )
        self.assertIs(
            MessageObservationPoint.ACCEPTANCE,
            view.messages[1].observation_point,
        )
        exported = view.to_dict()
        self.assertEqual(
            ["exchange", "acceptance"],
            [
                message["observation_point"]
                for message in exported["messages"]
            ],
        )
        json.dumps(exported)

    def test_acceptance_timeline_has_one_flat_receiver_lane_per_channel(
        self,
    ) -> None:
        view = TransactionTimeSpaceView(
            name="accepted observations",
            lifelines=(
                TimeSpaceLifeline("requester", "Requester"),
                TimeSpaceLifeline("home", "Home"),
            ),
            messages=(
                TimeSpaceMessage(
                    "flow:message:0",
                    "op",
                    "requester",
                    "home",
                    2,
                    "ReadUnique accepted",
                    channel="REQ",
                    observation_point=MessageObservationPoint.ACCEPTANCE,
                ),
                TimeSpaceMessage(
                    "flow:message:1",
                    "op",
                    "home",
                    "requester",
                    4,
                    "CompData accepted",
                    channel="DAT",
                    observation_point=MessageObservationPoint.ACCEPTANCE,
                ),
            ),
            time_basis=TimeBasis.MODEL_STEP,
        )

        timeline = transaction_semantic_wavejson(view)

        self.assertIn("accepted semantic events", timeline["head"]["text"])
        self.assertEqual(
            ["MODEL STEP", "requester · DAT", "home · REQ"],
            [lane["name"] for lane in timeline["signal"]],
        )
        self.assertTrue(
            all(isinstance(lane, dict) for lane in timeline["signal"])
        )
        rendered = json.dumps(timeline)
        self.assertEqual(1, rendered.count("ReadUnique accepted"))
        self.assertEqual(1, rendered.count("CompData accepted"))
        self.assertNotIn("Requester (requester)", rendered)
        self.assertNotIn("Home (home)", rendered)
        self.assertNotIn("/ tx", rendered)
        self.assertNotIn("/ rx", rendered)

    def test_mixed_timeline_places_acceptance_only_at_destination(
        self,
    ) -> None:
        view = TransactionTimeSpaceView(
            name="mixed observations",
            lifelines=(
                TimeSpaceLifeline("requester", "Requester"),
                TimeSpaceLifeline("home", "Home"),
            ),
            messages=(
                TimeSpaceMessage(
                    "exchange",
                    "op",
                    "requester",
                    "home",
                    0,
                    "exchange event",
                    channel="REQ",
                ),
                TimeSpaceMessage(
                    "acceptance",
                    "op",
                    "requester",
                    "home",
                    1,
                    "destination-only acceptance",
                    channel="REQ",
                    observation_point=MessageObservationPoint.ACCEPTANCE,
                ),
            ),
        )

        timeline = transaction_semantic_wavejson(view)
        requester_group = timeline["signal"][1]
        home_group = timeline["signal"][2]
        requester_text = json.dumps(requester_group)
        home_text = json.dumps(home_group)

        self.assertEqual(
            "semantic transaction timeline",
            timeline["head"]["text"].split(" · ")[-1],
        )
        self.assertEqual("Requester (requester)", requester_group[0])
        self.assertEqual("Home (home)", home_group[0])
        self.assertNotIn("destination-only acceptance", requester_text)
        self.assertEqual(1, home_text.count("destination-only acceptance"))
        self.assertEqual(1, json.dumps(timeline).count("destination-only acceptance"))
        self.assertIn("REQ / accept", home_text)

    def test_time_space_channel_palette_has_a_stable_legend_order(
        self,
    ) -> None:
        view = TransactionTimeSpaceView(
            name="channel palette",
            lifelines=(
                TimeSpaceLifeline("a", "A"),
                TimeSpaceLifeline("b", "B"),
            ),
            messages=(
                TimeSpaceMessage("dat", "op", "a", "b", 0, "data", channel="DAT"),
                TimeSpaceMessage("rsp", "op", "b", "a", 1, "response", channel="RSP"),
                TimeSpaceMessage("snp", "op", "a", "b", 2, "snoop", channel="SNP"),
                TimeSpaceMessage("req", "op", "b", "a", 3, "request", channel="REQ"),
            ),
        )

        dot = transaction_time_space_dot(view)

        self.assertIn('color="#2563a8"', dot)
        self.assertIn('color="#c46a00"', dot)
        self.assertIn('color="#247148"', dot)
        self.assertIn('color="#7c4aa5"', dot)
        self.assertLess(dot.index("REQ · request"), dot.index("SNP · snoop"))
        self.assertLess(
            dot.index("SNP · snoop"),
            dot.index("RSP · response/credit"),
        )
        self.assertLess(
            dot.index("RSP · response/credit"),
            dot.index("DAT · data/copyback"),
        )

    def test_model_step_allows_simultaneous_events(self) -> None:
        view = TransactionTimeSpaceView(
            name="parallel events",
            lifelines=(
                TimeSpaceLifeline("a", "A"),
                TimeSpaceLifeline("b", "B"),
                TimeSpaceLifeline("c", "C"),
            ),
            messages=(
                TimeSpaceMessage("e0", "op", "a", "b", 4, "first"),
                TimeSpaceMessage("e1", "op", "a", "c", 4, "second"),
            ),
            time_basis=TimeBasis.MODEL_STEP,
        )

        timeline = transaction_semantic_wavejson(view)

        self.assertEqual(["4"], timeline["signal"][0]["data"])
        self.assertIn("first", timeline["signal"][1][1]["data"][0])
        self.assertIn("second", timeline["signal"][1][1]["data"][0])

    def test_unknown_refs_duplicate_event_index_and_backwards_edges_fail(
        self,
    ) -> None:
        lifelines = (
            TimeSpaceLifeline("a", "A"),
            TimeSpaceLifeline("b", "B"),
        )
        with self.assertRaisesRegex(ValueError, "unknown lifeline"):
            TransactionTimeSpaceView(
                "bad endpoint",
                lifelines,
                (TimeSpaceMessage("e0", "op", "a", "missing", 0, "bad"),),
            )
        with self.assertRaisesRegex(ValueError, "unique event times"):
            TransactionTimeSpaceView(
                "duplicate index",
                lifelines,
                (
                    TimeSpaceMessage("e0", "op", "a", "b", 0, "one"),
                    TimeSpaceMessage("e1", "op", "b", "a", 0, "two"),
                ),
            )
        with self.assertRaisesRegex(ValueError, "earlier time"):
            TransactionTimeSpaceView(
                "backwards cause",
                lifelines,
                (
                    TimeSpaceMessage("e0", "op", "a", "b", 0, "one"),
                    TimeSpaceMessage("e1", "op", "b", "a", 1, "two"),
                ),
                causal_edges=(TimeSpaceCausalEdge("e1", "e0", "bad"),),
            )

    def test_equal_step_causal_cycle_is_rejected(self) -> None:
        lifelines = (
            TimeSpaceLifeline("a", "A"),
            TimeSpaceLifeline("b", "B"),
        )
        with self.assertRaisesRegex(ValueError, "causal cycle"):
            TransactionTimeSpaceView(
                "cycle",
                lifelines,
                (
                    TimeSpaceMessage("e0", "op", "a", "b", 0, "one"),
                    TimeSpaceMessage("e1", "op", "b", "a", 0, "two"),
                ),
                causal_edges=(
                    TimeSpaceCausalEdge("e0", "e1", "first"),
                    TimeSpaceCausalEdge("e1", "e0", "second"),
                ),
                time_basis=TimeBasis.MODEL_STEP,
            )

    def test_non_timeline_time_basis_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "event_index or model_step"):
            TransactionTimeSpaceView(
                name="bad basis",
                lifelines=(TimeSpaceLifeline("a", "A"),),
                state_changes=(
                    TimeSpaceStateChange(
                        "state",
                        "op",
                        "a",
                        0,
                        "before",
                        "after",
                        "state",
                    ),
                ),
                messages=(),
                time_basis=TimeBasis.CLOCK_TICK,
            )


if __name__ == "__main__":
    unittest.main()
