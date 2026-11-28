"""Rehearse manually removing attribution cues from invented reports."""

reports = {
    "standalone": "Prepared by the Nexus arm.\nThe west ramp is locked (`notes/access.txt:4`).\n",
    "inline": "Finding (independent arm): the east ramp closes at 18:00 (`notes/access.txt:7`).\n",
    "namesake": "The Nexus Room is upstairs (`notes/floorplan.txt:2`).\n",
    "citation": "The map omits the stair count (`runs/solo/map.txt:9`).\n",
    "claim": "The operator reports that only the Nexus arm saw the updated map (`notes/intake.txt:5`).\n",
    "uncertain": "The second worker's route matches the checklist (`notes/routes.txt:3`).\n",
}

# These are hand-checked expectations, independent of the proposed edits.
expected = {
    "standalone": "The west ramp is locked (`notes/access.txt:4`).\n",
    "inline": "Finding: the east ramp closes at 18:00 (`notes/access.txt:7`).\n",
    "namesake": "The Nexus Room is upstairs (`notes/floorplan.txt:2`).\n",
}

# Apply only the two deletions identified by the operator in these fixtures.
reviewer_reports = {
    "standalone": reports["standalone"].removeprefix("Prepared by the Nexus arm.\n"),
    "inline": reports["inline"].replace(" (independent arm)", "", 1),
    "namesake": reports["namesake"],
}
withheld = {
    "citation": "The pinned citation path identifies the arm",
    "claim": "Attribution is part of the claim",
    "uncertain": "The worker reference may change the meaning if removed",
}

assert set(reviewer_reports) == set(expected), "Only reports that can be blinded belong in the reviewer packet"
assert set(withheld) == reports.keys() - reviewer_reports.keys()
for case, text in reviewer_reports.items():
    assert text.encode() == expected[case].encode(), f"{case}: claim or citation changed, or attribution remains"
print("PASS: two attribution cues removed and one legitimate name retained; claims and citations byte-identical")
for case, reason in withheld.items():
    print(f"WITHHELD: {case}: {reason}")
print("No rubric decisions or scores; fictional reports only.")
