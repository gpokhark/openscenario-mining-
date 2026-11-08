"""Action and trigger vocabularies, derived from the ASAM OpenSCENARIO 1.x XSD.

Terms are the standard's own element names in snake_case; nothing is invented
or merged. The grouping element the standard places an action under becomes its
`family`. The tables below only say where to descend: PrivateAction and
GlobalAction wrap either a family element holding the concrete action
(LongitudinalAction > SpeedAction) or the concrete action directly
(TeleportAction). Unknown elements are kept under their own name with family
"other" so nothing is dropped. See docs/step4-vocabulary.md.
"""
import re

# family element -> family name; the concrete action is its first child
PRIVATE_GROUPS = {
    "LongitudinalAction": "longitudinal", "LateralAction": "lateral",
    "ControllerAction": "controller", "RoutingAction": "routing",
    "AppearanceAction": "appearance", "TrailerAction": "trailer",
}
# concrete actions that sit directly under PrivateAction
PRIVATE_DIRECT = {
    "VisibilityAction": "visibility", "SynchronizeAction": "synchronize",
    "ActivateControllerAction": "controller", "TeleportAction": "teleport",
}
GLOBAL_GROUPS = {
    "EntityAction": "entity", "ParameterAction": "parameter",
    "InfrastructureAction": "infrastructure", "TrafficAction": "traffic",
}
GLOBAL_DIRECT = {"EnvironmentAction": "environment", "SetMonitorAction": "monitor",
                 "VariableAction": "variable"}
# SetAction/ModifyAction are only meaningful under ParameterAction
QUALIFIED = {"SetAction": "ParameterSetAction", "ModifyAction": "ParameterModifyAction"}
# wrapper below a family element that is itself not the concrete action
PASS_THROUGH = {"TrafficSignalAction"}


def snake(tag):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", tag).lower()


def _first_child(el):
    return next((c for c in el if isinstance(c.tag, str)), None)


def classify_action(el):
    """el is a GlobalAction, PrivateAction or UserDefinedAction.
    -> list of (family, term), one per concrete action it holds.

    A family element can hold several concrete actions (ControllerAction holds
    both AssignControllerAction and OverrideControllerValueAction), and a
    UserDefinedAction wraps a CustomCommandAction; all are returned."""
    tag = el.tag
    if tag == "UserDefinedAction":
        leaves = [snake(c.tag) for c in el if isinstance(c.tag, str)]
        return [("user_defined", t) for t in leaves] or [("user_defined", "user_defined_action")]
    kids = [c for c in el if isinstance(c.tag, str)]
    if not kids:
        return [("other", snake(tag))]
    if tag == "PrivateAction":
        groups, direct = PRIVATE_GROUPS, PRIVATE_DIRECT
    else:
        groups, direct = GLOBAL_GROUPS, GLOBAL_DIRECT
    out = []
    for child in kids:
        if child.tag in direct:
            out.append((direct[child.tag], snake(child.tag)))
        elif child.tag in groups:
            leaves = [c for c in child if isinstance(c.tag, str)]
            while leaves and all(l.tag in PASS_THROUGH for l in leaves):
                leaves = [c for l in leaves for c in l if isinstance(c.tag, str)]
            for leaf in leaves or [child]:
                out.append((groups[child.tag], snake(QUALIFIED.get(leaf.tag, leaf.tag))))
        else:
            out.append(("other", snake(child.tag)))
    return out


def classify_condition(cond):
    """cond is a Condition element. -> trigger term (standard element name, snake_case)"""
    kind = _first_child(cond)
    if kind is None:
        return "other"
    if kind.tag == "ByEntityCondition":
        for c in kind:
            if isinstance(c.tag, str) and c.tag == "EntityCondition":
                leaf = _first_child(c)
                return snake(leaf.tag) if leaf is not None else "other"
        return "other"
    if kind.tag == "ByValueCondition":
        leaf = _first_child(kind)
        return snake(leaf.tag) if leaf is not None else "other"
    return snake(kind.tag)
