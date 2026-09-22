import json

import pytest

from jev_ra.browser import actions
from jev_ra.decide import Reply
from jev_ra.decide.policy import (
    Decision,
    InvalidDecision,
    build_questions,
    build_state,
    read_answers,
)
from jev_ra.decide.questions import NEXT_ACTION, NONE_VALUE, PAGE_TEXT_CHARS, TARGET

PAGE = {
    "url": "http://127.0.0.1/form.html",
    "title": "Booking form",
    "text": "Booking form",
    "elements": [
        {"ref": "e1", "node": 1, "role": "textbox", "label": "City", "value": "Zurich", "rect": {}},
        {"ref": "e2", "node": 2, "role": "combobox", "label": "Cabin", "value": "Economy", "rect": {}},
        {"ref": "e3", "node": 3, "role": "button", "label": "Search flights", "rect": {}},
    ],
    "actions": [
        {"id": "e1", "node": 1, "role": "textbox", "kind": "fill", "label": "City", "value": "Zurich"},
        {"id": "e1", "node": 1, "role": "textbox", "kind": "click", "label": "Open City", "value": "Zurich"},
        {
            "id": "e2",
            "node": 2,
            "role": "combobox",
            "kind": "select",
            "label": "Cabin → Business",
            "value": "business",
            "current_value": "Economy",
        },
        {"id": "e3", "node": 3, "role": "button", "kind": "click", "label": "Search flights"},
        {"id": "wait", "kind": "wait", "label": "Wait for the page to update"},
    ],
    "omitted": 0,
}

CLICK_ONLY = {
    "elements": [{"ref": "e1", "node": 1, "role": "link", "label": "Gödel", "rect": {}}],
    "actions": [{"id": "e1", "node": 1, "role": "link", "kind": "click", "label": "Gödel"}],
    "omitted": 0,
}


def space_for(page=PAGE):
    return actions.build(page)


def reply_with(**answers):
    return Reply(answers=answers, latency_ms=310, usage={"cost": 0.0002})


OPERATION_SPREAD = {"CLICK": 0.6, "TYPE_TEXT": 0.2, "SELECT": 0.1, "WAIT": 0.05, "DONE": 0.03, "BLOCKED": 0.02}


def choice_answer(value, probabilities=None, confidence=0.8):
    probabilities = probabilities or {value: 1.0}
    return {"choice": value, "confidence": confidence, "probabilities": probabilities}


def test_questions_cover_only_the_operations_this_page_offers():
    questions = build_questions(space_for(), "book a flight")
    assert set(questions) == {"operation", "click_target", "type_text_target", "select_target", "goal_achieved"}
    assert set(questions["operation"]["criteria"]) == {
        "CLICK",
        "TYPE_TEXT",
        "SELECT",
        "WAIT",
        "DONE",
        "BLOCKED",
    }
    assert set(questions["click_target"]["criteria"]) == {"e1", "e3"}
    assert set(questions["select_target"]["criteria"]) == {"e2:1"}


def test_a_click_only_page_asks_no_type_or_select_question():
    questions = build_questions(space_for(CLICK_ONLY), "open the article")
    assert set(questions) == {"operation", "click_target", "goal_achieved"}
    assert set(questions["operation"]["criteria"]) == {"CLICK", "DONE", "BLOCKED"}


def test_value_for_field_appears_only_with_values_and_a_typeable_field():
    assert "value_for_field" not in build_questions(space_for(), "goal")
    assert "value_for_field" not in build_questions(space_for(CLICK_ONLY), "goal", values={"city": "London"})
    questions = build_questions(space_for(), "goal", values={"city": "London", "notes": "x" * 400})
    criteria = questions["value_for_field"]["criteria"]
    assert set(criteria) == {"city", "notes", NONE_VALUE}
    assert criteria["city"] == "city: London"
    assert criteria["notes"].endswith("…")
    assert len(criteria["notes"]) <= 128


def test_prev_ok_appears_only_once_there_is_history():
    assert "prev_ok" not in build_questions(space_for(), "goal")
    questions = build_questions(space_for(), "goal", history=[{"action": "Open City", "kind": "click"}])
    assert questions["prev_ok"]["type"] == "noul"
    assert set(questions["prev_ok"]["criteria"]) == {"true", "false"}


def test_every_criterion_and_instruction_is_a_string():
    questions = build_questions(space_for(), "goal", history=[{"action": "a"}], values={"city": "London"})
    for question in questions.values():
        assert isinstance(question["instructions"], str)
        assert all(isinstance(value, str) for value in question["criteria"].values())


def test_instructions_carry_the_goal_and_the_measured_rules_verbatim():
    questions = build_questions(space_for(), "book ZRH to LON")
    operation = json.loads(questions["operation"]["instructions"])
    assert operation["goal"] == "book ZRH to LON"
    assert operation["rules"] == NEXT_ACTION
    target = json.loads(questions["click_target"]["instructions"])
    assert target["rules"] == [NEXT_ACTION, TARGET]
    assert target["operation"] == "CLICK"


def test_target_criteria_render_ref_role_label_and_value():
    questions = build_questions(space_for(), "goal")
    assert questions["type_text_target"]["criteria"]["e1"] == "[e1] textbox City · Zurich"
    assert questions["select_target"]["criteria"]["e2:1"] == "[e2:1] combobox Cabin → Business · Economy"


def test_state_sends_meaning_and_recent_actions_only():
    space = space_for()
    history = [{"action": f"step {n}", "kind": "click", "text": None, "page_changed": True} for n in range(12)]
    state = build_state(PAGE, space, "goal", history, values={"city": "London"})
    assert state["page"] == {"url": PAGE["url"], "title": PAGE["title"], "text": PAGE["text"]}
    assert len(state["recent_actions"]) == 10
    assert state["recent_actions"][0]["action"] == "step 2"
    assert state["values_available"] == ["city"]
    assert all("rect" not in element for element in state["elements"])
    assert state["elements"][0] == {"ref": "e1", "role": "textbox", "label": "City", "value": "Zurich"}


def test_the_state_caps_the_page_text_it_carries():
    page = {**PAGE, "text": "x" * (PAGE_TEXT_CHARS * 3)}
    state = build_state(page, space_for(page), "goal")
    assert len(state["page"]["text"]) == PAGE_TEXT_CHARS


def test_the_panel_a_click_opened_is_listed_first_and_its_control_says_so():
    space = space_for()
    opened = {"node": 3, "controls": {1, 2}}
    state = build_state(PAGE, space, "goal", opened=opened)
    assert [element["ref"] for element in state["elements"]] == ["e1", "e2", "e3"]
    opener = state["elements"][-1]
    assert (opener["ref"], opener["expanded"]) == ("e3", "true")


def test_a_panel_below_its_button_is_hoisted_above_it():
    space = space_for()
    state = build_state(PAGE, space, "goal", opened={"node": 1, "controls": {3}})
    assert [element["ref"] for element in state["elements"]] == ["e3", "e1", "e2"]
    assert state["elements"][1]["expanded"] == "true"


def test_a_field_with_its_list_open_is_not_a_click_target():
    questions = build_questions(space_for(), "goal", opened={"node": 1, "controls": {4}, "listbox": True})
    assert "e1" not in questions["click_target"]["criteria"]
    assert "e3" in questions["click_target"]["criteria"]
    assert "e1" in questions["type_text_target"]["criteria"]


LISTING = {
    **PAGE,
    "elements": [
        {"ref": "e1", "node": 1, "role": "combobox", "label": "Origin", "value": "Zur", "expanded": "true", "rect": {}},
        {"ref": "e2", "node": 2, "role": "option", "label": "Zurich Airport (ZRH)", "rect": {}},
        {"ref": "e3", "node": 3, "role": "button", "label": "Search flights", "rect": {}},
    ],
    "actions": [
        {"id": "e1", "node": 1, "role": "combobox", "kind": "fill", "label": "Origin", "value": "Zur"},
        {"id": "e1", "node": 1, "role": "combobox", "kind": "click", "label": "Open Origin", "value": "Zur"},
        {"id": "e2", "node": 2, "role": "option", "kind": "click", "label": "Zurich Airport (ZRH)"},
        {"id": "e3", "node": 3, "role": "button", "kind": "click", "label": "Search flights"},
    ],
}


def test_a_combobox_that_says_its_list_is_open_is_not_a_click_target():
    questions = build_questions(space_for(LISTING), "goal")
    assert "e1" not in questions["click_target"]["criteria"]
    assert {"e2", "e3"} <= set(questions["click_target"]["criteria"])
    assert "e1" in questions["type_text_target"]["criteria"]


def test_it_says_so_even_when_the_step_that_opened_it_is_out_of_reach():
    # Google Flights replaces the field with the panel it opened, so the node the last step named
    # is not on the page any more. The page's own expanded is what is left to read.
    questions = build_questions(space_for(LISTING), "goal", opened={"node": 99, "controls": {98}, "listbox": True})
    assert "e1" not in questions["click_target"]["criteria"]


def test_an_expanded_control_with_no_options_up_is_still_a_click_target():
    no_options = {**LISTING, "elements": [LISTING["elements"][0], LISTING["elements"][2]]}
    assert "e1" in build_questions(space_for(no_options), "goal")["click_target"]["criteria"]


def test_a_combobox_that_says_nothing_about_itself_stays_on_offer():
    quiet = dict(LISTING)
    quiet["elements"] = [{k: v for k, v in e.items() if k != "expanded"} for e in LISTING["elements"]]
    assert "e1" in build_questions(space_for(quiet), "goal")["click_target"]["criteria"]


def test_an_opened_panel_that_is_not_a_list_leaves_every_click_on_offer():
    questions = build_questions(space_for(), "goal", opened={"node": 1, "controls": {4}, "listbox": False})
    assert "e1" in questions["click_target"]["criteria"]


def test_without_an_opened_panel_the_table_keeps_its_document_order():
    state = build_state(PAGE, space_for(), "goal")
    assert [element["ref"] for element in state["elements"]] == ["e1", "e2", "e3"]
    assert all("expanded" not in element for element in state["elements"])


def test_the_state_names_what_the_last_step_opened():
    space = space_for(LISTING)
    state = build_state(LISTING, space, "goal", opened={"node": 1, "controls": {2}, "listbox": True})
    assert state["last_step_effect"] == "the last step opened 1 suggestions under Origin, listed first below"


def test_a_panel_is_named_as_controls_rather_than_suggestions():
    space = space_for()
    state = build_state(PAGE, space, "goal", opened={"node": 3, "controls": {1, 2}, "listbox": False})
    assert state["last_step_effect"] == "the last step opened 2 controls under Search flights, listed first below"


def test_a_step_that_opened_nothing_says_nothing():
    assert "last_step_effect" not in build_state(PAGE, space_for(), "goal")
    gone = {"node": 1, "controls": {98, 99}, "listbox": True}
    assert "last_step_effect" not in build_state(PAGE, space_for(), "goal", opened=gone)


def test_the_questions_are_not_reworded_by_any_of_this():
    space = space_for(LISTING)
    plain = build_questions(space, "goal")
    opened = build_questions(space, "goal", opened={"node": 1, "controls": {2}, "listbox": True})
    assert plain["operation"]["instructions"] == opened["operation"]["instructions"]
    assert json.loads(plain["operation"]["instructions"])["rules"] == NEXT_ACTION


def test_read_answers_resolves_the_action_and_the_joint_probability():
    space = space_for()
    questions = build_questions(space, "goal")
    reply = reply_with(
        operation=choice_answer("CLICK", OPERATION_SPREAD),
        click_target=choice_answer("e3", {"e1": 0.3, "e3": 0.7}),
        goal_achieved={"noul": 0.1},
    )
    decision = read_answers(space, questions, reply)
    assert isinstance(decision, Decision)
    assert (decision.operation, decision.target) == ("CLICK", "e3")
    assert decision.action["label"] == "Search flights"
    assert decision.probability == pytest.approx(0.42)
    assert decision.goal_achieved == 0.1
    assert decision.latency_ms == 310
    assert decision.cost == pytest.approx(0.0002)
    assert not decision.terminal


def test_read_answers_accepts_controls_and_terminals_without_a_target():
    space = space_for()
    questions = build_questions(space, "goal")
    wait = read_answers(space, questions, reply_with(operation=choice_answer("WAIT"), goal_achieved={"noul": 0.0}))
    assert wait.action["kind"] == "wait"
    assert wait.target is None
    done = read_answers(space, questions, reply_with(operation=choice_answer("DONE"), goal_achieved={"noul": 0.9}))
    assert done.terminal
    assert done.action is None


def test_read_answers_rejects_a_target_outside_the_observed_space():
    space = space_for()
    questions = build_questions(space, "goal")
    reply = reply_with(operation=choice_answer("CLICK"), click_target=choice_answer("e9"), goal_achieved={"noul": 0.0})
    with pytest.raises(InvalidDecision) as raised:
        read_answers(space, questions, reply)
    assert (raised.value.operation, raised.value.target) == ("CLICK", "e9")


def test_read_answers_binds_a_host_value_and_treats_none_as_unbound():
    space = space_for()
    values = {"city": "London"}
    questions = build_questions(space, "goal", values=values)
    base = {
        "operation": choice_answer("TYPE_TEXT"),
        "type_text_target": choice_answer("e1"),
        "goal_achieved": {"noul": 0.0},
    }
    bound = read_answers(space, questions, reply_with(**base, value_for_field=choice_answer("city")))
    assert bound.value_name == "city"
    unbound = read_answers(space, questions, reply_with(**base, value_for_field=choice_answer(NONE_VALUE)))
    assert unbound.value_name is None


def test_a_corrective_re_ask_removes_the_invalid_combination():
    space = space_for()
    pruned = build_questions(space, "goal", exclude={("CLICK", "e3")})
    assert set(pruned["click_target"]["criteria"]) == {"e1"}
    assert "CLICK" in pruned["operation"]["criteria"]
    without_click = build_questions(space, "goal", exclude={("CLICK", "e1"), ("CLICK", "e3")})
    assert "click_target" not in without_click
    assert "CLICK" not in without_click["operation"]["criteria"]
    assert "WAIT" not in build_questions(space, "goal", exclude={("WAIT", None)})["operation"]["criteria"]


def test_candidates_are_ranked_by_joint_probability():
    space = space_for()
    questions = build_questions(space, "goal")
    reply = reply_with(
        operation=choice_answer("CLICK", OPERATION_SPREAD),
        click_target=choice_answer("e3", {"e1": 0.3, "e3": 0.7}),
        type_text_target=choice_answer("e1", {"e1": 1.0}),
        select_target=choice_answer("e2:1", {"e2:1": 1.0}),
        goal_achieved={"noul": 0.1},
    )
    candidates = read_answers(space, questions, reply).candidates
    probabilities = [item["probability"] for item in candidates]
    assert probabilities == sorted(probabilities, reverse=True)
    assert candidates[0] == {
        "operation": "CLICK",
        "target": "e3",
        "label": "[e3] button Search flights",
        "probability": pytest.approx(0.42),
    }
    assert candidates[1]["operation"] == "TYPE_TEXT"


def test_candidates_stop_at_eight():
    refs = range(1, 21)
    links = {
        "elements": [{"ref": f"e{n}", "node": n, "role": "link", "label": f"Result {n}"} for n in refs],
        "actions": [{"id": f"e{n}", "node": n, "role": "link", "kind": "click", "label": f"Result {n}"} for n in refs],
    }
    space = space_for(links)
    questions = build_questions(space, "goal")
    spread = {f"e{n}": (0.81 if n == 1 else 0.01) for n in range(1, 21)}
    reply = reply_with(
        operation=choice_answer("CLICK", {"CLICK": 0.9, "DONE": 0.07, "BLOCKED": 0.03}),
        click_target=choice_answer("e1", spread),
        goal_achieved={"noul": 0.1},
    )
    assert len(read_answers(space, questions, reply).candidates) == 8
