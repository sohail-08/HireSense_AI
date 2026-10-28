"""Documentation must match the real graph topology, without invoking workflows."""
import pytest
from scripts.check_langgraph_diagrams import ROOT, check_diagrams, graph_inventory


@pytest.mark.skipif(not (ROOT / "docs" / "langgraphs").is_dir(), reason="Source diagrams are not packaged in the runtime image")
def test_editable_diagrams_match_all_seven_compiled_graphs():
    inventory = graph_inventory()
    assert len(inventory) == 7
    assert sum(len(item["nodes"]) - 2 for item in inventory) == 35
    assert sum(len(item["edges"]) for item in inventory) == 44
    check_diagrams(inventory)
